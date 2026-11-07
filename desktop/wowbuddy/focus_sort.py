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


def _merge_trimmed(left, right, health):
    # 0308a0先裁剪已就位的前后缀；其比较顺序对NaN有可观察影响。
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


def health_order(health):
    items = list(range(len(health)))
    if len(items) <= 32:
        return _insertion(items, health)
    # 0326d0正常缓冲区足够容纳ceil(n/2)，各半独立块归并后裁剪合并。
    middle = (len(items) + 1) // 2
    return _merge_trimmed(_buffered(items[:middle], health),
                          _buffered(items[middle:], health), health)
