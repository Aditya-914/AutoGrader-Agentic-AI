#include <stdio.h>

/*
 * Inefficient implementation:
 * Adds by looping a times (O(N) instead of O(1)).
 */
int main(void) {
    long long a, b;
    if (scanf("%lld %lld", &a, &b) != 2) {
        return 1;
    }
    
    long long sum = b;
    if (a > 0) {
        for (long long i = 0; i < a; i++) {
            sum++;
        }
    } else {
        for (long long i = 0; i < -a; i++) {
            sum--;
        }
    }
    
    printf("%lld\n", sum);
    return 0;
}
