"""无人托管状态机：状态持有、阶段判定与每帧动作输出。

UnattendedController 是各行程状态（练级、固定点、补给、复活、交任务、拾取接近）的唯一持有者，
DevWindow 上同名的 _xxx 属性只是委托到这里。每帧：
  phase(session)     把这些状态汇总为一个显式阶段 UnattendedPhase；
  frame_plan(...)    由总开关与独立开关得出本帧启用的复活/练级/导航；
  run_frame(FrameInput, plan)  每帧输入会话、开关与本帧解码的 CharacterState/DeathState，按序产出
                     本帧动作 FrameAction（交任务前置条件由角色状态与行程状态判定），窗口逐项执行。
阶段判定与动作产出是纯 Python，不依赖 Qt、Win32 或窗口对象；动作的执行由 revival / vendor / leveling
三个阶段处理器完成（unattended_phases），处理器经传入的窗口（host）收发按键与写日志。

阶段判定与拆分前 poll_once 中的布尔表达式逐项等价：任一赶路类行程属于当前会话即为 is_travel；
LOOT 排在所有赶路类阶段之后且不计入 is_travel。多个行程同时成立时按 classify 中的顺序取第一个。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from wowbuddy.automation.unattended_phases import LevelingPhase, RevivalPhase, VendorPhase


class UnattendedPhase(Enum):
    IDLE = 'idle'
    DEAD = 'dead'                  # 自动复活中，角色为尸体
    GHOST = 'ghost'                # 自动复活中，角色为灵魂
    POST_REVIVAL = 'post_revival'  # 复活后等待重新接路
    VENDOR = 'vendor'              # 修理/补给：等待、在线补给行程或商人跑腿
    QUEST = 'quest'                # 交任务行程
    TRAVEL = 'travel'              # 前往练级点的行程
    CAMP = 'camp'                  # 等待前往固定打怪点
    UPGRADE = 'upgrade'            # 等待升级后换练级点
    LOOT = 'loot'                  # 走向尸体拾取（不属于托管赶路）

    @property
    def is_travel(self) -> bool:
        """是否按"托管赶路中"处理本帧；IDLE 与 LOOT 不算，与拆分前的布尔表达式一致。"""
        return self not in (UnattendedPhase.IDLE, UnattendedPhase.LOOT)


class FrameAction(Enum):
    """本帧按序执行的托管处理步骤。"""
    REVIVAL = 'revival'        # 死亡/灵魂状态跟踪、跑尸记录与自动复活
    VENDOR = 'vendor'          # 修理与补给
    QUEST = 'quest'            # 交任务行程
    LEVELING = 'leveling'      # 练级行程与飞行恢复；本帧交任务行程已接管时跳过
    NAVIGATION = 'navigation'  # 执行当前导航目标


@dataclass(frozen=True)
class UnattendedSnapshot:
    """窗口上各行程字段的只读快照；缺失的字段用 None。"""
    leveling_trip: Any = None        # (…, …, trip)，trip 有 session/complete
    fixed_camp_route: Any = None
    leveling_upgrade_wait: Any = None  # 会话键
    vendor_wait: Any = None          # (会话键, …)
    automatic_revival: Any = None    # 有 session/life
    post_revival_session: Any = None
    online_vendor: Any = None        # ((会话键, …), …)
    quest_trip: Any = None           # 有 session
    vendor_run: Any = None           # 有 session/active
    loot_approach_session: Any = None  # 正在走向尸体拾取的会话键


def classify(snapshot: UnattendedSnapshot, session) -> UnattendedPhase:
    s = snapshot
    revival = s.automatic_revival
    if revival is not None and revival.session == session and revival.life in ('dead', 'ghost'):
        return UnattendedPhase.DEAD if revival.life == 'dead' else UnattendedPhase.GHOST
    if s.post_revival_session == session:
        return UnattendedPhase.POST_REVIVAL
    if ((s.vendor_wait is not None and s.vendor_wait[0] == session)
            or (s.online_vendor is not None and s.online_vendor[0][0] == session)
            or (s.vendor_run is not None and s.vendor_run.session == session and s.vendor_run.active)):
        return UnattendedPhase.VENDOR
    if s.quest_trip and s.quest_trip.session == session:
        return UnattendedPhase.QUEST
    active = s.leveling_trip
    if active and active[2].session == session and not active[2].complete:
        return UnattendedPhase.TRAVEL
    if s.fixed_camp_route is not None and (not active or active[2].session != session):
        return UnattendedPhase.CAMP
    if s.leveling_upgrade_wait == session:
        return UnattendedPhase.UPGRADE
    if s.loot_approach_session is not None and s.loot_approach_session == session:
        return UnattendedPhase.LOOT
    return UnattendedPhase.IDLE


@dataclass(frozen=True)
class FramePlan:
    """本帧启用的托管处理器；总开关打开时三者全开，否则各自取独立开关。"""
    revive: bool
    leveling: bool
    navigate: bool


@dataclass(frozen=True)
class FrameInput:
    """一帧的输入：会话、开关，以及本帧从像素条解码出的角色与死亡状态。"""
    session: Any
    unattended: bool
    frame_ok: bool
    image_ok: bool = True
    character: Any = None   # engine.character_state.CharacterState（route_character 结果）；本帧未解码时为 None
    death: Any = None       # engine.character_state.DeathState；未启用复活时为 None


class UnattendedController:
    """无人托管行程状态的唯一持有者。字段含义见 UnattendedSnapshot。"""
    FIELDS = tuple(UnattendedSnapshot.__dataclass_fields__)

    def __init__(self, vendor_run=None):
        for name in self.FIELDS:
            setattr(self, name, None)
        self.vendor_run = vendor_run
        self.last_phase = UnattendedPhase.IDLE
        self.last_character = None
        self.last_death = None
        # 各阶段处理器（见 unattended_phases）：REVIVAL / VENDOR / LEVELING 动作由它们执行。
        self.revival = RevivalPhase()
        self.vendor = VendorPhase()
        self.leveling = LevelingPhase()

    def snapshot(self) -> UnattendedSnapshot:
        return UnattendedSnapshot(**{name: getattr(self, name) for name in self.FIELDS})

    def phase(self, session) -> UnattendedPhase:
        self.last_phase = classify(self.snapshot(), session)
        return self.last_phase

    def travel_active(self, session, *, unattended: bool, monitoring: bool) -> bool:
        """管线是否按"托管赶路中"处理本帧（拆分前的 pipeline.unattended_travel）。"""
        return bool(unattended and monitoring and self.phase(session).is_travel)

    def frame_phase(self, frame: FrameInput) -> UnattendedPhase:
        """本帧阶段：死亡状态解码为尸体/灵魂时直接取 DEAD/GHOST，否则按行程状态判定。

        只用于状态记录与显示；管线的 unattended_travel 仍按 travel_active（行程状态）计算。
        """
        death = frame.death
        if death is not None and getattr(death, 'life', None) in ('dead', 'ghost'):
            return UnattendedPhase.DEAD if death.life == 'dead' else UnattendedPhase.GHOST
        return classify(self.snapshot(), frame.session)

    def quest_gate_open(self, frame: FrameInput) -> bool:
        """交任务步骤的前置条件：帧有效、角色存活，且不在补给或复活后接路中。"""
        character = frame.character
        vendor_busy = (self.vendor_run is not None and self.vendor_run.active) or self.online_vendor or self.vendor_wait
        return bool(frame.image_ok and frame.frame_ok and character is not None and character.life == 'alive'
                    and not vendor_busy and self.post_revival_session != frame.session)

    def run_frame(self, frame: FrameInput, plan: FramePlan):
        """状态机的一帧：按序产出本帧动作（生成器）。

        每产出一个动作后暂停，窗口执行该动作再继续，因此后续判断看到的是前序动作更新后的状态。
        QUEST 由窗口以 send() 回传交任务结果；结果非空时本帧跳过 LEVELING。
        """
        self.last_character, self.last_death = frame.character, frame.death
        self.last_phase = self.frame_phase(frame)
        if plan.revive:
            yield FrameAction.REVIVAL
        if frame.unattended and plan.navigate and frame.frame_ok:
            yield FrameAction.VENDOR
        quest = None
        if frame.unattended and plan.navigate:
            if self.quest_gate_open(frame):
                quest = yield FrameAction.QUEST
            else:
                self.quest_trip = None
        if plan.leveling and quest is None:
            yield FrameAction.LEVELING
        yield FrameAction.NAVIGATION

    @staticmethod
    def frame_plan(unattended: bool, *, auto_revive: bool, auto_leveling: bool, auto_navigate: bool) -> FramePlan:
        return FramePlan(revive=unattended or auto_revive, leveling=unattended or auto_leveling,
                         navigate=unattended or auto_navigate)


def delegated(field: str):
    """生成把窗口属性委托到 self.unattended.<field> 的 property；删除时复位为 None。"""
    return property(lambda self: getattr(self.unattended, field),
                    lambda self, value: setattr(self.unattended, field, value),
                    lambda self: setattr(self.unattended, field, None))
