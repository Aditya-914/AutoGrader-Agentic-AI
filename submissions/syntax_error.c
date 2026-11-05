#include <stdio.h>

/*
 * Demonstration of compilation failure:
 * Missing semicolons and type mismatch.
 */
int main(void) {
    int a, b
    scanf("%d %d", &a, &b)
    printf("%d\n", a + b)
    return 0;
}
