import random
from collections import Counter

def most_common_number(start, end, repetitions=1000):
    """Generate random numbers and return the most common one."""
    numbers = [random.randint(start, end) for _ in range(repetitions)]
    counter = Counter(numbers)
    return counter.most_common(1)[0]
