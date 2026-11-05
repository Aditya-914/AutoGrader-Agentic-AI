#include <stdio.h>

/* Modular helper function using 64-bit integers to prevent overflow */
long long add_safe(long long a, long long b) {
    return a + b;
}

int main(void) {
    long long x, y;
    if (scanf("%lld %lld", &x, &y) == 2) {
        printf("%lld\n", add_safe(x, y));
    }
    return 0;
}
