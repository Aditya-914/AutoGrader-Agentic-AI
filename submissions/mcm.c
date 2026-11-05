#include <stdio.h>

int main(void) {
    float a, b;
    scanf("%f %f", &a, &b);
    if(b!=0)
    {
        float c=(float)a/b;
        printf("%0.2f\n",c);
    }
    else
    printf("Divide by 0 is invalid\n");
    return 0;
}
