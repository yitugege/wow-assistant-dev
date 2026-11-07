"""00E730/00D930/00D7F0：四值目录评分排序，保留同分交换顺序。"""


def sort_candidates(candidates):
    items = list(candidates)
    if any(rank not in (0, 1, 2, 3) for rank, _ in items):
        raise ValueError('原目录评分仅为0至3')

    def swap(a, b):
        items[a], items[b] = items[b], items[a]

    def less(a, b):
        return items[a][0] < items[b][0]

    def median(a, b, c):
        if less(b, a):
            swap(b, a)
        if less(c, b):
            swap(c, b)
            if less(b, a):
                swap(b, a)

    def partition(first, last):
        mid, end = first + (last - first) // 2, last - 1
        if end - first > 40:
            step = (last - first) // 8
            median(first, first + step, first + 2 * step)
            median(mid - step, mid, mid + step)
            median(end - 2 * step, end - step, end)
            median(first + step, mid, end - step)
        else:
            median(first, mid, end)
        low, high = mid, mid + 1
        while low > first and items[low - 1][0] == items[low][0]:
            low -= 1
        while high < last and items[high][0] == items[low][0]:
            high += 1
        right, left = high, low
        while True:
            while right < last:
                if less(low, right):
                    right += 1
                elif less(right, low):
                    break
                else:
                    swap(high, right)
                    high += 1
                    right += 1
            while left > first:
                probe = left - 1
                if less(probe, low):
                    left -= 1
                elif less(low, probe):
                    break
                else:
                    low -= 1
                    swap(low, probe)
                    left -= 1
            if left == first and right == last:
                return low, high
            if left == first:
                if high != right:
                    swap(low, high)
                swap(low, right)
                low += 1
                high += 1
                right += 1
            elif right == last:
                left -= 1
                low -= 1
                if left != low:
                    swap(left, low)
                high -= 1
                swap(low, high)
            else:
                left -= 1
                swap(right, left)
                right += 1

    def sort(first, last):
        if last - first <= 32:
            for index in range(first + 1, last):
                value, hole = items[index], index
                while hole > first and value[0] < items[hole - 1][0]:
                    items[hole] = items[hole - 1]
                    hole -= 1
                items[hole] = value
            return
        low, high = partition(first, last)
        # 每次移除一个完整评分等值区，最多四层；该四值域不会耗尽
        # 原初始n、每轮3/4递减的预算，故不会到达通用堆排序分支。
        sort(first, low)
        sort(high, last)

    sort(0, len(items))
    return items
