
#include <limits.h>
#include <stdio.h>

int findminDistance(int dist[], int included[], int V)
{
    int min = INT_MAX;
    int min_index = -1;

    for (int v = 0; v < V; v++) {
        if (!included[v] && dist[v] <= min) {
            min = dist[v];
            min_index = v;
        }
    }

    return min_index;
}

void printSolution(int dist[], int V)
{
    printf("Shortest distances from source vertex 0:\n");

    for (int i = 0; i < V; i++) {
        if (dist[i] == INT_MAX)
            printf("INF ");
        else
            printf("%d ", dist[i]);
    }

    printf("\n");
}

void DijkstrasAlgo(int V, int graph[V][V], int src)
{
    int dist[V];
    int included[V];

    for (int i = 0; i < V; i++) {
        dist[i] = INT_MAX;
        included[i] = 0;
    }

    dist[src] = 0;

    for (int count = 0; count < V - 1; count++) {

        int u = findminDistance(dist, included, V);

        // Stop if no reachable vertex remains
        if (u == -1)
            break;

        included[u] = 1;

        for (int v = 0; v < V; v++) {

            if (!included[v] &&
                graph[u][v] > 0 &&
                dist[u] != INT_MAX &&
                dist[u] + graph[u][v] < dist[v]) {

                dist[v] = dist[u] + graph[u][v];
            }
        }
    }

    printSolution(dist, V);
}

int main()
{
    int V;

    scanf("%d", &V);

    int graph[V][V];

    for (int i = 0; i < V; i++) {
        for (int j = 0; j < V; j++) {
            scanf("%d", &graph[i][j]);
        }
    }

    DijkstrasAlgo(V, graph, 0);

    return 0;
}

