
#include <stdio.h>
#include <stdbool.h>
#include <string.h>

const char direction[] = "DLRU";
const int dr[] = {1, 0, 0, -1};
const int dc[] = {0, -1, 1, 0};

bool isValid(int r, int c, int n, int m, int maze[n][m]) {
    return r >= 0 && c >= 0 &&
           r < n && c < m && maze[r][c] == 1;
}

void solve(int r, int c, int n, int m,
           int maze[n][m], char path[],
           char ans[][100], int *count) {

    if (r == n - 1 && c == m - 1) {
        strcpy(ans[*count], path);
        (*count)++;
        return;
    }

    maze[r][c] = 0;

    for (int i = 0; i < 4; i++) {
        int nr = r + dr[i];
        int nc = c + dc[i];

        if (isValid(nr, nc, n, m, maze)) {
            int len = strlen(path);
            path[len] = direction[i];
            path[len + 1] = '\0';

            solve(nr, nc, n, m, maze, path, ans, count);

            path[len] = '\0';
        }
    }

    maze[r][c] = 1;
}

void findPath(int n, int m, int maze[n][m]) {
    if (maze[0][0] == 0 || maze[n-1][m-1] == 0) {
        printf("-1");
        return;
    }

    char path[100] = "";
    char ans[100][100];
    int count = 0;

    solve(0, 0, n, m, maze, path, ans, &count);

    if (count == 0) {
        printf("-1");
    } else {
        for (int i = 0; i < count; i++) {
            printf("%s ", ans[i]);
        }
    }
}

int main() {
    int n, m;
    scanf("%d%d", &n, &m);

    int maze[n][m];

    for (int i = 0; i < n; i++) {
        for (int j = 0; j < m; j++) {
            scanf("%d", &maze[i][j]);
        }
    }

    findPath(n, m, maze);

    return 0;
}

