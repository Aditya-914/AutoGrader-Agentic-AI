#include <stdio.h>

int main(void) {
    int a, b;
    scanf("%d %d", &a, &b);
    if(!b)
    printf("%f\n", (float)a/b);
    else
    printf("Divide by 0 is invalid\n");
    return 0;
}
