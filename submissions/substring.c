#include <stdio.h>
#include <string.h>

/**
 * Counts substrings containing at least one occurrence of characters a, b, and c.
 */
int numberOfSubstrings(char* s) {
    int lastSeen[3] = {-1, -1, -1};
    int count = 0;

    for (int i = 0; s[i] != '\0'; i++) {
        if (s[i] >= 'a' && s[i] <= 'c') {
            lastSeen[s[i] - 'a'] = i;
        }
        if (lastSeen[0] != -1 && lastSeen[1] != -1 && lastSeen[2] != -1) {
            int minIndex = lastSeen[0];
            if (lastSeen[1] < minIndex) minIndex = lastSeen[1];
            if (lastSeen[2] < minIndex) minIndex = lastSeen[2];
            count += 1 + minIndex;
        }
    }
    return count;
}

int main(void) {
    char s[100005];
    if (scanf("%100004s", s) == 1) {
        printf("%d\n", numberOfSubstrings(s));
    }
    return 0;
}
