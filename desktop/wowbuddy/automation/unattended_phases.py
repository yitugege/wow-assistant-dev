"""无人托管各阶段的处理器：复活、补给与练级。

2026-11-15 从 DevWindow 原样移出（方法体中 self 改为 host，其余语句未改）。
UnattendedController 持有这些处理器；run_frame 产出 FrameAction 后，窗口经同名委托方法调用到这里。
host 为窗口：处理器只经它读写行程状态（已委托到 UnattendedController）、发送按键与写日志，本模块不导入 Qt。
"""
from wowbuddy.automation.vendor_run import VendorRun, vendor_due

_PATROL_RADIUS = 30
_REJOIN_FAR_YARDS = 40       # 离录制轨迹超过该距离时提示“直线接回”
_REJOIN_OFF_LEG_YARDS = 12   # 行程中离本段轨迹超过该距离视为被拉离
_REJOIN_INTERVAL_MS = 3000   # 同一段重新规划的最短间隔


class RevivalPhase:
    """UnattendedPhase.DEAD / GHOST / POST_REVIVAL：死亡跟踪、跑尸记录与自动复活。"""

    def frame(self, host, session, result, image, frame, death, *, navigate, unattended):
        """FrameAction.REVIVAL：死亡状态跟踪、跑尸路线记录与自动复活。"""
        from wowbuddy.engine.character_state import decode_navigation_state
        in_combat = bool(frame and frame.values.get('player_in_combat') == 'ON')
        position = None
        if navigate and death:
            if death.life == 'ghost':
                position = decode_navigation_state(image, frame, for_revival=True)
            elif death.life == 'alive' and host._automatic_revival is not None:
                position = decode_navigation_state(image, frame, for_target=in_combat)
        trail = (host._corpse_trail.observe(session, death, position,
                                          now_ms=host.monotonic_ms(),
                                          enabled=host._record_corpse_action.isChecked())
                 if navigate else None)
        if navigate and host._corpse_trail.notice:
            host.logger.append(host._corpse_trail.notice)
        if trail:
            try:
                host.settings.save_corpse_trail(trail)
            except OSError as error:
                host.logger.append('跑尸路线保存失败。' + str(error))
            else:
                host.logger.append(f'已记录本次成功的跑尸路线，共 {trail.count(":")} 段。')
                exit_route = host._corpse_trail.exit_route
                if exit_route:
                    host._remember_graveyard_exit(exit_route, scale=host._corpse_trail.exit_scale)
        nearby = str(frame.values.get('enemies_8yd', '')) if frame and frame.ok else ''
        host._poll_revival(session, death, result.capture.client_rect if result.capture else None,
                           position=position, in_combat=in_combat,
                           recovery_ready=bool(result.tick and result.tick.decision.recovery_ready),
                           nearby_hostile=nearby.isdecimal() and int(nearby) > 0,
                           prefer_clearance=unattended and navigate)

    def poll(self, host, session, state, rect, *, prefer_clearance=False, **readings):
        revival = host._automatic_revival
        if revival is None:
            if state is None or state.life not in ('dead', 'ghost'):
                return
            from wowbuddy.automation.death_recovery import AutomaticRevival
            from wowbuddy.win32.windows_mouse import Win32Mouse
            mouse = Win32Mouse(host.sender.backend, host.monitor.backend)
            revival = host._automatic_revival = AutomaticRevival(mouse, stop_movement=host._release_navigation_key,
                                                                 in_foreground=mouse.in_foreground)
        revival.prefer_clearance = prefer_clearance
        previous_life = revival.life if revival.session == session else None
        status = revival.observe(session, session[0], state, rect, host.monotonic_ms(), **readings)
        revived = previous_life in ('dead', 'ghost') and revival.life == 'alive'
        if previous_life != revival.life:
            host._corpse_trip = host._corpse_access = None
            host._ghost_origin = None
            host._grid_corpse_trip = host._grid_corpse_given_up = None
            if revival.life in ('dead', 'ghost'):
                host._vendor_run.interrupt(session)
            cached = host._local_access
            if cached and cached[0] == session:
                cached[1].pop('ghost', None)
                if revived and (living_access := cached[1].get('alive')):
                    living_access.resume_after_revival()
        active = host._leveling_trip
        if revived:
            host._post_revival_session = session
            host._post_revival_notice = False
            if active and active[2].session == session and not active[2].complete:
                active[2].resume_after_revival()
        if status:
            host.logger.append(status)

class VendorPhase:
    """UnattendedPhase.VENDOR：背包满或装备红时的补给往返。"""

    def poll(self, host, session, image, frame, result, character):
        from wowbuddy.engine.character_state import decode_navigation_state, decode_vendor_state
        from wowbuddy.core.dev_protocol import bag_recovery_walk_safe

        sale = decode_vendor_state(image, frame)
        repair = decode_vendor_state(image, frame, repair=True)
        trip = host._leveling_trip
        active = trip[2] if trip and trip[2].session == session else None
        online = host._online_vendor
        supplying = host._vendor_run.active or online is not None
        repairing = host._vendor_run.repair if supplying else bool(repair and repair.repair_needed)
        reading = repair if repairing else sale
        if online:
            context, outbound, returning = online
            original_key = context[1]
            route_changed = character and (character.faction, character.map_id, character.zone) != (
                original_key[0], original_key[2], original_key[3])
            if (context[0] != session
                    or route_changed
                    or active not in (outbound, returning)):
                host._online_vendor = None
                host._vendor_run = VendorRun()
                if active in (outbound, returning):
                    host._leveling_trip = None
                return
            if character and trip[1] != character.level:
                active.level = character.level
                host._leveling_trip = character.faction, character.level, active
            if active is returning:
                if not (returning.complete and character and frame.values.get('player_in_combat') == 'OFF'):
                    return
                position = decode_navigation_state(image, frame)
                if position is not None and not position.moving and returning.goal.contains(position):
                    host._online_vendor = None
                    host._clear_vendor_travel()
                    if character.level != original_key[1]:
                        host._leveling_trip = host._leveling_destination = None
                    else:
                        host._leveling_destination = session, character.route_key, returning.goal
                return
        if reading is None:
            return
        position = decode_navigation_state(image, frame) if character and reading else None
        if online is None and position and host._resume_vendor_travel(session, character, position, sale, repair):
            return
        if reading.free > 0 and not repairing:
            host._vendor_wait = None
            host._vendor_recovery_walk = None
            host._bag_full_session = None
        arrived = bool(active and active.complete and active.goal.label == '补给商人'
                       and position and active.goal.contains(position))
        fields = frame.values
        recovering = host._post_revival_session == session
        recovery = result.tick.decision if result.tick else None
        bag_ready = (reading.free == 0 and recovery is not None and bag_recovery_walk_safe(frame)
                     and any(item.action == 'recovery_bag_full' for item in recovery.candidates))
        ready = bool(position and not position.moving and result.tick and result.tick.selected is None
                     and fields.get('player_in_combat') == 'OFF'
                     and (recovery.recovery_ready or bag_ready or (arrived and not recovering)))
        catalog = online[0][2] if online else host._vendor_route is None
        manual_fixed = not catalog and host._fixed_camp_route is not None
        compatible = reading.catalog == catalog and (reading.select_key or reading.selected or reading.matched)
        if not compatible:
            if ready and repairing:
                host._wait_for_vendor(session, '装备耐久已变红，当前没有可用的修理商人绑定。')
            elif ready and reading.free == 0:
                if host._bag_full_grinding_enabled():
                    # 兜底（docs/design/20261117-loop-issues.md L1）：没有商人时不停，继续打怪、暂不拾取。
                    if host._bag_full_session != session:
                        host._bag_full_session = session
                        host.logger.append('背包已满且没有可用的商人，继续打怪，暂不拾取。'
                                           '绑定商人（/wbdvendor 与“设置商人路线…”）后会自动去出售。')
                else:
                    host._wait_for_vendor(session, '普通背包已满，当前没有可用的补给商人绑定，暂停练级。')
            return
        if online is None and not manual_fixed:
            if not (ready and (repairing or vendor_due(reading))):
                return
            online = host._plan_online_vendor(session, character, position, active, catalog=catalog, repair=repairing)
            if online is None:
                if repairing:
                    host._wait_for_vendor(session, '装备耐久已变红，当前位置没有可接入的修理往返路线。')
                elif reading.free == 0:
                    host._wait_for_vendor(session, '普通背包已满，当前位置没有可接入的商人往返路线，暂停练级。')
                return
        host._vendor_wait = None
        was_active = host._vendor_run.active and host._vendor_run.session == session
        status = host._vendor_run.observe(session, reading, host.monotonic_ms(), ready=ready, arrived=arrived,
            send=lambda action, value: host._send_travel_ui_action(session[0], fields, result.capture.client_rect,
                                                                    action, value))
        if host._patrol_route is not None and not was_active and host._vendor_run.active:
            host._patrol_kill = None
        if online and not was_active and host._vendor_run.active:
            host._online_vendor = online
            host._vendor_departure_free = reading.free
            host._leveling_trip = character.faction, character.level, online[1]
            host._leveling_destination = host._camp_scout = host._local_access = None
            host._save_vendor_travel(session, character, returning=False)
        elif online and was_active and not host._vendor_run.active:
            online[2].level = character.level
            host._leveling_trip = character.faction, character.level, online[2]
            host._save_vendor_travel(session, character, returning=True)
        if bag_ready and ready and host._vendor_run.active:
            host._vendor_recovery_walk = session
        if status:
            host.logger.append(status)
        if arrived and host._vendor_run.active:
            host.ui.suggestions.setPlainText(status or host._vendor_run.notice
                                             or '已到商人坐标，等待游戏确认出售和背包状态。')

    def wait(self, host, session, reason):
        if host._vendor_wait != (session, reason):
            host._vendor_wait = session, reason
            host.logger.append(reason)

class LevelingPhase:
    """UnattendedPhase.TRAVEL / CAMP / UPGRADE：练级点规划、固定打怪点与升级换点。"""

    def frame(self, host, session, image, frame, character, *, navigate, unattended):
        """FrameAction.LEVELING：飞行中恢复练级行程，否则推进练级规划。"""
        from wowbuddy.engine.character_state import decode_navigation_state
        flight = None
        active = host._leveling_trip
        if (unattended and navigate and not (active and active[2].session == session)
                and image is not None and frame and frame.ok):
            from wowbuddy.engine.character_state import decode_character_state, decode_taxi_state
            flight = decode_taxi_state(image, frame)
        if flight and flight.riding:
            if host._fixed_camp_route is None:
                host._resume_leveling_travel(session, character or decode_character_state(image, frame), flying=True)
        else:
            host._poll_leveling(session, character, navigate,
                                navigation=lambda: decode_navigation_state(image, frame)
                                if image is not None and frame and frame.ok else None)

    def poll(self, host, session, character, navigate, *, navigation=None):
        from wowbuddy.automation.leveling_route import local_camp_on_current_shore, write_leveling_result
        grinding = host.grind_check.isChecked()
        if grinding and navigate and host._online_vendor and host._online_vendor[0][0] == session:
            return
        if grinding and navigate and host._fixed_camp_route is not None:
            host._poll_fixed_camp(session, character)
            return
        active = host._leveling_trip
        if active is not None:
            faction, level, trip = active
            if trip.session != session:
                host._leveling_trip = None
            elif character is None:
                return
            elif (character.faction, character.level) == (faction, level):
                host._leveling_upgrade_wait = None
                if trip.is_recent_crossing_return(character.map_id, host.monotonic_ms()):
                    return
                if not trip.complete or character.map_id == trip.goal.map_id:
                    if (not grinding or trip.connecting or trip.manual_camp_pending
                            or local_camp_on_current_shore(character, trip.goal)):
                        return
                    host._replan_local_camp()
                host._leveling_trip = None
            elif (grinding and navigate and character.faction == faction
                  and character.level > level):
                finishing_connection = trip.needs_safe_handoff(character.map_id, host.monotonic_ms())
                if host._leveling_upgrade_wait != session:
                    host._leveling_upgrade_wait = session
                    if finishing_connection:
                        host.logger.append(f'已升到 {character.level} 级，走完当前换图接入路段后重新选点。')
                if finishing_connection or character.x is None or character.y is None:
                    return
        plan = host._leveling_destination
        if grinding and character and plan and plan[:2] == (session, character.route_key):
            if local_camp_on_current_shore(character, plan[2]):
                return
            host._replan_local_camp()
        planner = host._planner_for_character(character)
        if planner is None:
            return
        if (grinding and navigate and host._leveling_upgrade_wait != session
                and host._resume_leveling_travel(session, character, navigation=navigation)):
            return
        connections = host._connection_legs() if navigate else ()
        camp_routes = tuple(host._manual_routes(connections=connections)) if grinding and navigate else ()
        options = {'connections': connections} if connections else {}
        if camp_routes:
            options['camp_routes'] = camp_routes
        if (grinding and navigate and character and character.faction == 'alliance'
                and character.map_id in (1438, 1457) and character.level is not None and character.level >= 12):
            options['allow_taxi'] = True
        lookup = planner.observe(session, character, host.monotonic_ms(), grinding=grinding, **options)
        if lookup is not None:
            if lookup['ok']:
                point = lookup['point']
                applied = True
                if not navigate:
                    host._leveling_trip = host._leveling_destination = None
                elif lookup['cross_zone']:
                    applied = host._plan_land_travel(session, character, point, lookup)
                else:
                    host._set_local_camp(session, character, point)
                if applied:
                    host._leveling_camps = list(lookup.get('alternatives', ()))
                    host._leveling_upgrade_wait = None
                if grinding and navigate:
                    if applied and host._leveling_trip is not None:
                        host._save_leveling_travel(session, character, host._leveling_trip[2])
                    elif applied:
                        host._clear_leveling_travel()
                    else:
                        # 后台查询结束时，已导入的连接或角色位置可能已经变了。
                        planner.retire_point(session, character, point['zone'], point['x'], point['y'],
                                             host.monotonic_ms())
                        lookup = dict(lookup, ok=False, error='目的地的陆路已不可达，将重新查询练级点。')
            try:
                write_leveling_result(host.launch_options.data_dir/'leveling-auto.json', lookup)
            except OSError as error:
                host.logger.append('无法保存自动练级查询结果。' + str(error))
            else:
                if lookup['ok']:
                    point = lookup['point']
                    if lookup.get('cached_sources'):
                        host.logger.append('攻略暂时无法读取，已用近期校验过的攻略重新选点。')
                    host.logger.append(f"下一处练级点为{point['zone']} · {point['name']} ({point['x']}, {point['y']})")
                else:
                    host.logger.append('自动练级查询失败。' + lookup['error'])

    @staticmethod
    def _displaced_from_leg(host, patrol, character):
        """录制路线行程中是否被拉离本段轨迹（如打怪后），且接回起点已变化：是则需要重新规划本段。"""
        from wowbuddy.automation.manual_routes import nearest_on_loop, path_distance
        planned = host._patrol_leg
        if planned is None or planned[0] != host._patrol_index or character.map_id != patrol.map_id:
            return False
        xy = character.x, character.y
        if path_distance(patrol, xy, planned[1]) <= _REJOIN_OFF_LEG_YARDS:
            return False
        if nearest_on_loop(patrol, xy)[0] == planned[2]:
            return False   # 仍在直线接回同一个起点，不重复规划
        now = host.monotonic_ms()
        if host._patrol_replan_ms is not None and now - host._patrol_replan_ms < _REJOIN_INTERVAL_MS:
            return False
        host._patrol_replan_ms = now
        return True

    def fixed_camp(self, host, session, character):
        from dataclasses import replace
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.walking_route import (WalkingTrip, auberdine_overlapping_floor, camp_access_road,
                                           darkshore_camp_origin, darkshore_south_camp, plan_walking_route,
                                           source_road_blocks)

        if (character is None or character.life != 'alive' or character.map_id is None
                or character.level is None or character.x is None or character.y is None):
            return
        selling = host._vendor_run.session == session and host._vendor_run.active and host._vendor_route is not None
        route = host._vendor_route if selling else host._fixed_camp_route
        patrol = host._patrol_route if not selling else None
        recorded = patrol is not None and patrol.recorded
        if patrol is not None:
            # 规划范围以当前停留点为准；录制路线的实际道路在下方“接回轨迹”后确定。
            route = replace(patrol, points=(patrol.points[host._patrol_index],))
        scope = session, character.faction, character.level, route, selling
        if host._fixed_camp_blocked == (scope, character.map_id):
            return
        active = host._leveling_trip
        if host._fixed_camp_scope == scope and active and (active[2].connecting or character.map_id == route.map_id):
            if not (recorded and self._displaced_from_leg(host, patrol, character)):
                return
        if recorded:
            from wowbuddy.automation.manual_routes import nearest_on_loop, patrol_rejoin
            index, leg, distance = patrol_rejoin(patrol, (character.x, character.y), host._patrol_index)
            count = len(patrol.points)
            if count > 1 and index == (host._patrol_index - 1) % count:
                # 刚完成的停留点就在身边：不退回，沿完整的本段轨迹前往当前停留点。
                from wowbuddy.automation.manual_routes import patrol_leg
                index, leg = host._patrol_index, patrol_leg(patrol, host._patrol_index)
            if index != host._patrol_index:
                host.logger.append(f'接回录制路线，从第 {index + 1} 个停留点继续。')
                host._patrol_index = index
            if distance is not None and distance > _REJOIN_FAR_YARDS:
                host.logger.append(f'离录制路线约 {distance:.0f} 码，正直线接回。')
            route = replace(patrol, points=leg)
            scope = (session, character.faction, character.level, replace(patrol, points=(patrol.points[index],)),
                     selling)
            start = patrol.path.index(leg[0]) if leg[0] in patrol.path else 0
            # 偏离判断用“本段起点前一个轨迹点 + 本段路点”，本段只剩一个点时也能量出横向偏离。
            host._patrol_leg = (index, (patrol.path[start - 1],) + tuple(leg),
                                nearest_on_loop(patrol, (character.x, character.y))[0])
        host._fixed_camp_scope = scope
        host._fixed_camp_blocked = None
        host._leveling_trip = host._leveling_destination = host._camp_scout = None
        host._leveling_camps = []
        host._leveling_checkpoint_session = None
        connections = host._connection_legs()
        x, y = route.endpoint
        entry = route.points[0] if route.map_id == 1439 else (x, y)
        legs = plan_walking_route(character.map_id, route.map_id, character.level, 'alive',
                                  connections=connections, origin=(character.x, character.y),
                                  blocked_legs=source_road_blocks(character.map_id, character.x, character.y,
                                                                  elevation=character.elevation),
                                  faction=character.faction, destination_xy=entry, allow_taxi=True)
        label = '补给商人' if selling else '固定打怪点'
        if patrol is not None:
            label = host._patrol_label(host._patrol_index)
        radius = 5 if selling else _PATROL_RADIUS if patrol is not None else None
        goal = MapDestination(route.map_id, x, y, 'alive', label, radius=radius)
        if legs is None:
            host._wait_for_fixed_camp(character, f'暂无可达{label}的陆路')
            return
        road = ()
        if character.map_id == route.map_id and route.map_id in (1438, 1439, 1457) and len(route.points) == 1:
            road = camp_access_road(goal, origin=character)
        arrived = f'已到{label}，开始寻找目标。' if not selling else '已到商人坐标。'
        options = dict(level=character.level, camp_road=road or route.points, catalog_goal=None if road else goal,
                       connections=connections, catalog_zone=route.zone or None, faction=character.faction,
                       arrival_message=arrived, finish_in_range=patrol is not None)
        if (character.map_id == route.map_id == 1439 and auberdine_overlapping_floor(character.x, character.y)
                and not darkshore_camp_origin(character.x, character.y, elevation=character.elevation)):
            if not darkshore_south_camp(*entry):
                host._wait_for_fixed_camp(character, '奥伯丁飞行台尚未接入地面道路')
                return
            trip = WalkingTrip.resume_auberdine(session, goal, **options)
        else:
            trip = WalkingTrip(session, legs, goal, **options)
        host._leveling_trip = character.faction, character.level, trip
        host.logger.append(f'{label}位于地图 {route.map_id} ({x:.2f}, {y:.2f})。')
