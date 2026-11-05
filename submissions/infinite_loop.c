#include <stdio.h>

/*
 * Demonstration of infinite loop bug:
 * Smoke test and Phase 1 coordinator will catch this via RLIMIT_CPU and timeout!
 */
int main(void) {
    int a, b;
    scanf("%d %d", &a, &b);
    
    // Unintentional infinite loop
    while (1) {
        a = a + 0;
    }
    
    printf("%d\n", a + b);
    return 0;
}
