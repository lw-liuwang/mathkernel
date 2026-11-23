#include <stddef.h>

void fusion_baseline(size_t n, const double *restrict a, const double *restrict b,
                     const double *restrict c, const double *restrict d,
                     double *restrict first, double *restrict second, double *restrict out) {
    for (size_t i = 0; i < n; ++i) first[i] = a[i] * b[i];
    for (size_t i = 0; i < n; ++i) second[i] = first[i] + c[i];
    for (size_t i = 0; i < n; ++i) out[i] = second[i] * d[i];
}

void matmul_baseline(size_t n, const double *restrict a,
                     const double *restrict b, double *restrict out) {
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < n; ++j) {
            double value = 0.0;
            for (size_t k = 0; k < n; ++k) value = value + a[i * n + k] * b[k * n + j];
            out[i * n + j] = value;
        }
    }
}
