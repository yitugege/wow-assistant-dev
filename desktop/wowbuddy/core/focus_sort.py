"""原031570/0326d0治疗索引排序；保留NaN下的比较和移动顺序。"""


def _insertion(items, health):
    items = list(items)
    for position in range(1, len(items)):
        item = items[position]
        if health[items[0]] > health[item]:
            items[1:position + 1] = items[:position]
            items[0] = item
        else:
            slot = position
            while slot > 0 and health[items[slot - 1]] > health[item]:
                items[slot] = items[slot - 1]
                slot -= 1
            items[slot] = item
    return items


def _buffered(items, health):
    # 030d40：每32项插入排序，再按32、64、128...宽度归并。
    chunks = [_insertion(items[start:start + 32], health) for start in range(0, len(items), 32)]
    while len(chunks) > 1:
        merged = []
        for start in range(0, len(chunks), 2):
            if start + 1 == len(chunks):
                merged.append(chunks[start])
                continue
            left, right = chunks[start:start + 2]
            output = []
            i = j = 0
            while i < len(left) and j < len(right):
                # 原comisd/jbe在unordered时也取左项。
                if health[left[i]] > health[right[j]]:
                    output.append(right[j]); j += 1
                else:
                    output.append(left[i]); i += 1
            merged.append(output + left[i:] + right[j:])
        chunks = merged
    return chunks[0] if chunks else []


def _merge_trimmed(left, right, health, capacity=None):
    # 0308a0先裁剪已就位的前后缀；其比较顺序对NaN有可观察影响。
    if not left or not right:
        return left + right
    first = 0
    while first < len(left) and not health[left[first]] > health[right[0]]:
        first += 1
    if first == len(left):
        return left + right
    prefix, left = left[:first], left[first:]
    end = len(right)
    while end > 1 and not health[left[-1]] > health[right[end - 1]]:
        end -= 1
    suffix, right = right[end:], right[:end]
    if len(right) == 1:
        return prefix + right + left + suffix
    if len(left) == 1:
        return prefix + right + left + suffix
    if capacity is not None and capacity < min(len(left), len(right)):
        # 0309f0：两侧均放不下时二分切割；0307a0旋转后分别合并。
        if len(right) < len(left):
            right_cut = len(right) // 2
            value = health[right[right_cut]]
            start, count = 0, len(left)
            while count:
                half = count // 2
                # 030cb4/comisd + jbe：unordered 也推进下界。
                if not health[left[start + half]] > value:
                    start += half + 1
                    count -= half + 1
                else:
                    count = half
            left_cut = start
        else:
            left_cut = len(left) // 2
            value = health[left[left_cut]]
            start, count = 0, len(right)
            while count:
                half = count // 2
                if health[right[start + half]] < value:
                    start += half + 1
                    count -= half + 1
                else:
                    count = half
            right_cut = start
        return (prefix
                + _merge_trimmed(left[:left_cut], right[:right_cut], health, capacity)
                + _merge_trimmed(left[left_cut:], right[right_cut:], health, capacity)
                + suffix)
    if len(left) <= len(right):
        # 0309f0左缓冲：首个右项和最后左项已由裁剪比较定位。
        output = [right[0]]
        i, j = 0, 1
        while i < len(left) - 1 and j < len(right):
            if health[left[i]] > health[right[j]]:
                output.append(right[j]); j += 1
            else:
                output.append(left[i]); i += 1
        if j == len(right):
            output += left[i:]
        else:
            output += right[j:] + left[i:]
    else:
        # 右缓冲从末端倒填，保留原强制首尾项顺序。
        reverse = [left[-1]]
        i, j = len(left) - 2, len(right) - 1
        while i >= 0 and j > 0:
            if health[left[i]] > health[right[j]]:
                reverse.append(left[i]); i -= 1
            else:
                reverse.append(right[j]); j -= 1
        if i < 0:
            reverse += right[:j + 1][::-1]
        else:
            reverse += left[:i + 1][::-1] + right[:j + 1][::-1]
        output = reverse[::-1]
    return prefix + output + suffix


def _allocate_buffer(size):
    return bytearray(size)


def _temporary_buffer(count):
    # 049735..0497b8：1024项栈空间始终可用；更大请求失败时折半。
    capacity = (count + 1) // 2
    if capacity <= 1024:
        return capacity, None
    while capacity:
        try:
            reserved = _allocate_buffer(capacity * 4)
        except MemoryError:
            capacity //= 2
            continue
        if capacity > 1024:
            return capacity, reserved
        # 原程序释放小于等于1024项的成功分配，改用固定栈缓冲区。
        return 1024, None
    return 1024, None


def health_order(health, *, buffer_capacity=None):
    """buffer_capacity 指定原临时缓冲区容量，用于受限容量路径对照。

    默认按原调用方申请临时容量并在该申请失败时回退。
    Python 中间列表仍需内存；这不是所有分配失败的恢复机制。
    """
    if buffer_capacity is not None and (not isinstance(buffer_capacity, int) or buffer_capacity < 0):
        raise ValueError('排序缓冲区容量必须是非负整数')
    items = list(range(len(health)))
    reserved = None
    if buffer_capacity is None and len(items) > 32:
        buffer_capacity, reserved = _temporary_buffer(len(items))
    # 保持容量预留存活到本次排序结束；中间列表异常仍向上传播。
    return _sort(items, health, buffer_capacity)


def _sort(items, health, capacity):
    if len(items) <= 32:
        return _insertion(items, health)
    # 0326d0正常缓冲区足够容纳ceil(n/2)，各半独立块归并后裁剪合并。
    middle = (len(items) + 1) // 2
    if capacity is not None and capacity < middle:
        return _merge_trimmed(_sort(items[:middle], health, capacity),
                              _sort(items[middle:], health, capacity), health, capacity)
    return _merge_trimmed(_buffered(items[:middle], health),
                          _buffered(items[middle:], health), health, capacity)
