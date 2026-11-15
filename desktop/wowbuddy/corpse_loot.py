"""用游戏原生交互键拾取当前目标，等待同一尸体的游戏回执。"""

from dataclasses import dataclass

_LOOT_BLOCKS = {
    1: '没有连续确认刚击杀目标的身份。',
    2: '游戏未确认自动拾取或原生交互键。',
    3: '找不到有效的游戏重选键。',
    4: '游戏未授予这具尸体的拾取权限。',
    5: '游戏未提供可读的尸体拾取状态。',
}


def _interaction_deadline(started, opened_at):
    if opened_at is None:
        return started + 3200
    return min(started + 11_200, opened_at + 8000)


@dataclass(slots=True)
class _SoftLoot:
    loot_id: int
    generation: int
    started: int
    sequence: int
    key: str
    opened_at: int | None = None
    retried: bool = False


class CorpseLoot:
    def __init__(self):
        self.session = None
        self.target = None
        self.sample = None
        self.attempts = 0
        self.first_attempt = 0
        self.last_attempt = 0
        self.opened_at = None
        self.loot_generation = None
        self.since = None
        self.finished = False
        self.engaged = False
        self.approaching = False
        self.retarget_attempts = 0
        self.retarget_at = None
        self.loot_block = 0
        self.soft_pending = None
        self.soft_handled = None
        self.combat_notices = None
        self.kill_notice_at = None

    def observe(self, session, mob, now_ms, send, log, *, approach, safe_to_loot, combat_notices=None):
        if session != self.session:
            self.__init__()
            self.session = session
        if combat_notices is not None:
            if self.combat_notices is not None and 0 < (combat_notices - self.combat_notices) % 65536 < 32768:
                self.kill_notice_at = now_ms
            self.combat_notices = combat_notices
        if (safe_to_loot and self.kill_notice_at is not None and now_ms - self.kill_notice_at < 800
                and (mob is None or mob.state in (0, 5)) and self.soft_pending is None):
            return '已收到战斗经验回执，等待尸体读数稳定。'
        if mob is None:
            return None
        if self.soft_pending is not None:
            pending = self.soft_pending
            loot_id = pending.loot_id
            elapsed = now_ms - pending.started
            if mob.loot_open and pending.opened_at is None:
                pending.opened_at = now_ms
            deadline = _interaction_deadline(pending.started, pending.opened_at)
            fresh = mob.sequence != pending.sequence
            pending.sequence = mob.sequence
            interrupted = not safe_to_loot or mob.state in (1, 2) or (mob.loot_id and mob.loot_id != loot_id)
            if interrupted:
                self.soft_pending = None
                self.soft_handled = loot_id, now_ms
                self.finished = True
            elif (not mob.loot_open and not mob.soft_corpse and mob.loot_generation != pending.generation
                  and (elapsed >= 1000 or (mob.state == 4 and mob.reacquired))):
                self.soft_pending = None
                self.soft_handled = loot_id, now_ms
                self.target, self.finished = mob.revision, True
                log('游戏已确认同一尸体的原生拾取窗口关闭。')
                return '拾取结束，等待下一帧再选怪。'
            elif now_ms < deadline:
                if (pending.opened_at is None and not pending.retried and elapsed >= 900 and fresh
                        and loot_id and mob.loot_id == loot_id and mob.soft_corpse and mob.key == pending.key
                        and mob.loot_generation == pending.generation):
                    pending.retried = True
                    if send(mob.key):
                        log('游戏仍确认同一尸体可拾取，已重试一次原生交互。')
                return '等待游戏确认同一尸体的交互结果。'
            else:
                self.soft_pending = None
                self.attempts, self.since = 0, None
                if mob.state != 6 or mob.loot_open:
                    self.soft_handled = loot_id, now_ms
                    self.target, self.finished = mob.revision, True
                    log('未确认原生拾取完成，已结束本次交互。')
                    return None
        if (mob.loot_id and self.soft_handled and mob.loot_id == self.soft_handled[0]
                and now_ms - self.soft_handled[1] < 4500):
            return None
        if mob.state == 7 and safe_to_loot:
            return '等待击杀回执和尸体状态稳定，再检查拾取和恢复。'
        if mob.revision != self.target:
            restored = self.retarget_attempts > 0 and mob.reacquired
            self.target, self.sample = mob.revision, None
            self.attempts, self.since, self.finished, self.approaching = 0, None, False, False
            self.opened_at = None
            self.engaged = restored
            self.loot_block = 0
            if self.retarget_attempts:
                if restored:
                    log('游戏已确认重选同一尸体。')
                else:
                    log('游戏未确认重选同一尸体，已停止本次拾取。')
            self.retarget_attempts = 0
            self.retarget_at = None
        fresh = mob.sequence != self.sample
        self.sample = mob.sequence
        if mob.soft_corpse and not self.finished:
            if self.retarget_attempts:
                self.since = None
            self.retarget_attempts = 0
            self.engaged = True
        if safe_to_loot and mob.loot_block and mob.loot_block != self.loot_block:
            self.loot_block = mob.loot_block
            log('拾取暂停。' + _LOOT_BLOCKS[mob.loot_block])
        if mob.state == 6 and safe_to_loot and not self.finished:
            if self.since is None:
                self.since = now_ms
            if now_ms - self.since >= 1500:
                self.finished = True
                if self.retarget_attempts:
                    log('游戏未确认重新选中尸体，已停止本次拾取。')
                    self.retarget_attempts = 0
                return None
            retry_ready = self.retarget_attempts == 1 and now_ms - self.retarget_at >= 550
            if fresh and (self.retarget_attempts == 0 or retry_ready) and send(mob.key):
                self.retarget_attempts += 1
                self.retarget_at = now_ms
                log(f'击杀后目标已清空，已发送游戏重选键 {mob.key}（第 {self.retarget_attempts} 次）。')
            return '等待游戏确认重新选中同一尸体。'
        if mob.state in (1, 2):
            self.engaged = mob.state == 1
        if not safe_to_loot or not self.engaged or self.finished or mob.state not in (3, 4, 5):
            return None
        if self.since is None:
            self.since = now_ms
        if self.attempts and mob.loot_generation != self.loot_generation and mob.state == 4 and not mob.loot_open:
            self.finished = True
            log('游戏已关闭拾取窗口，当前尸体不再报告可拾取。')
            return '拾取结束，等待下一帧再选怪。'
        if self.attempts:
            if mob.loot_open and self.opened_at is None:
                self.opened_at = now_ms
            deadline = _interaction_deadline(self.first_attempt, self.opened_at)
        else:
            deadline = self.since + (11_000 if self.approaching or mob.bearing is not None else 1200)
        if now_ms >= deadline:
            self.finished = True
            if self.attempts or mob.state == 3:
                log('尸体拾取未确认。请检查距离、背包和游戏内的自动拾取及交互绑定。')
            return None
        if mob.loot_open:
            return '游戏拾取窗口已打开，等待自动拾取完成。'
        if self.opened_at is not None:
            return '等待确认当前尸体的拾取状态，再继续选怪。'
        if mob.bearing is not None:
            # 接近控制器自己按定位帧去重。重复帧也要检查是否仍能持有前进键。
            self.approaching = True
            approach(mob.bearing)
            return '正在接近当前可拾取的尸体。'
        if fresh and mob.key and self.attempts < 2 and (not self.attempts or now_ms - self.last_attempt >= 900):
            if send(mob.key):
                if not self.attempts:
                    self.loot_generation = mob.loot_generation
                    self.first_attempt = now_ms
                self.attempts += 1
                self.last_attempt = now_ms
                if mob.soft_corpse:
                    self.soft_pending = _SoftLoot(mob.loot_id, mob.loot_generation, now_ms, mob.sequence, mob.key)
                log('游戏已确认同一尸体可直接交互，已发送原生拾取键。' if mob.soft_corpse
                    else '当前尸体可拾取，已发送游戏原生交互键。')
        return '等待确认当前尸体的拾取状态，再继续选怪。'
