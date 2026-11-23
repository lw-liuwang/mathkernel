#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static volatile double sink;

static double now_seconds(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) {
        perror("clock_gettime");
        exit(1);
    }
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

/* Independent recurrences expose throughput without permitting reassociation. */
static double compute_sample(size_t rounds) {
    double a = 0.1, b = 0.2, c = 0.3, d = 0.4;
    double e = 0.5, f = 0.6, g = 0.7, h = 0.8;
    const double scale = 0.99999999, step = 0.00000001;
    double start = now_seconds();
    for (size_t i = 0; i < rounds; ++i) {
        a = a * scale + step;
        b = b * scale + step;
        c = c * scale + step;
        d = d * scale + step;
        e = e * scale + step;
        f = f * scale + step;
        g = g * scale + step;
        h = h * scale + step;
    }
    double elapsed = now_seconds() - start;
    sink = a + b + c + d + e + f + g + h;
    return elapsed;
}

static double stream_sample(double *restrict out, const double *restrict in, size_t n) {
    double start = now_seconds();
    for (size_t i = 0; i < n; ++i) out[i] = in[i] + 1.0;
    double elapsed = now_seconds() - start;
    sink = out[n / 2];
    return elapsed;
}

int main(void) {
    const size_t n = (size_t)1 << 24, rounds = 20000000;
    double *in = malloc(n * sizeof(double)), *out = malloc(n * sizeof(double));
    if (!in || !out) {
        fprintf(stderr, "calibration allocation failed\n");
        free(in);
        free(out);
        return 1;
    }
    for (size_t i = 0; i < n; ++i) in[i] = (double)(i % 1024) / 1024.0;
    compute_sample(rounds);
    stream_sample(out, in, n);
    printf("{\"rounds\":%zu,\"stream_elements\":%zu,\"compute_seconds\":[", rounds, n);
    for (int i = 0; i < 7; ++i) printf("%s%.12g", i ? "," : "", compute_sample(rounds));
    printf("],\"stream_seconds\":[");
    for (int i = 0; i < 7; ++i) printf("%s%.12g", i ? "," : "", stream_sample(out, in, n));
    printf("]}\n");
    free(in);
    free(out);
    return 0;
}
