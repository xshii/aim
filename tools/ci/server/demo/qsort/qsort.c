/* qsort.c — 冒烟 demo：被测的“预生成代码”示例。
 * 实现快速排序，从命令行读整数，排序后输出。
 * CI 的运行型验证会编译并运行它，再与期望输出比对。
 */
#include <stdio.h>
#include <stdlib.h>

static void swap(int *a, int *b) { int t = *a; *a = *b; *b = t; }

static void qsort_impl(int *arr, int lo, int hi) {
    if (lo >= hi) return;
    int pivot = arr[(lo + hi) / 2];
    int i = lo, j = hi;
    while (i <= j) {
        while (arr[i] < pivot) i++;
        while (arr[j] > pivot) j--;
        if (i <= j) { swap(&arr[i], &arr[j]); i++; j--; }
    }
    qsort_impl(arr, lo, j);
    qsort_impl(arr, i, hi);
}

int main(int argc, char **argv) {
    int n = argc - 1;
    if (n <= 0) { printf("\n"); return 0; }
    int *arr = malloc(sizeof(int) * n);
    for (int i = 0; i < n; i++) arr[i] = atoi(argv[i + 1]);
    qsort_impl(arr, 0, n - 1);
    for (int i = 0; i < n; i++)
        printf("%d%s", arr[i], i + 1 < n ? " " : "\n");
    free(arr);
    return 0;
}
