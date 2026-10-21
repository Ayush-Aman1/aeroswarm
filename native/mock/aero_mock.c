/* Reference implementation of native/aeroswarm_native.h used by tests/test_native_adapter.py.
 * A trivially simple "engine": uniform wind of the inflow speed along the inflow direction, zero inside solids,
 * time-dependent sinusoidal gust, relayout that becomes ready after 3 polls. NOT physics - it only proves the ABI,
 * the ctypes wrapper and the relayout protocol. Copy this file as the skeleton for the real CUDA engine. */
#include "../aeroswarm_native.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

struct AeroEngine {
    int nx, ny, nz; float dx, dt; double t;
    uint8_t* solid; uint8_t* pending; float speed, dir, z0; float pspeed, pdir, pz0; int polls;
};
static char g_err[256] = "";

AERO_API int aero_abi_version(void) { return AERO_ABI_VERSION; }
AERO_API const char* aero_last_error(void) { return g_err; }

AERO_API AeroEngine* aero_create(int nx, int ny, int nz, float dx_m, float dt_s) {
    if (nx < 1 || ny < 1 || nz < 1) { strcpy(g_err, "bad grid"); return NULL; }
    AeroEngine* e = (AeroEngine*)calloc(1, sizeof(AeroEngine));
    e->nx = nx; e->ny = ny; e->nz = nz; e->dx = dx_m; e->dt = dt_s;
    e->solid = (uint8_t*)calloc((size_t)nx * ny * nz, 1);
    return e;
}
AERO_API void aero_destroy(AeroEngine* e) { if (e) { free(e->solid); free(e->pending); free(e); } }

AERO_API int aero_reset(AeroEngine* e, const uint8_t* solid, float speed, float dir, float z0) {
    memcpy(e->solid, solid, (size_t)e->nx * e->ny * e->nz);
    e->speed = speed; e->dir = dir; e->z0 = z0; e->t = 0;
    return 0;
}
AERO_API int aero_step(AeroEngine* e, int n) { e->t += n * e->dt; return 0; }

static float profile(AeroEngine* e, float z) {
    float zz = z < e->z0 ? e->z0 : z;
    return e->speed * logf(zz / e->z0) / logf(10.0f / e->z0);
}
static void vel_at(AeroEngine* e, float x, float y, float z, float* v) {
    int i = (int)(x / e->dx), j = (int)(y / e->dx), k = (int)(z / e->dx);
    if (i < 0) i = 0; if (j < 0) j = 0; if (k < 0) k = 0;
    if (i >= e->nx) i = e->nx - 1; if (j >= e->ny) j = e->ny - 1; if (k >= e->nz) k = e->nz - 1;
    if (e->solid[((size_t)i * e->ny + j) * e->nz + k]) { v[0] = v[1] = v[2] = 0; return; }
    float th = e->dir * 3.14159265f / 180.0f, u = profile(e, z) * (1.0f + 0.1f * sinf((float)e->t));
    v[0] = u * cosf(th); v[1] = u * sinf(th); v[2] = 0;
}
AERO_API int aero_sample(AeroEngine* e, const float* pos, int n, float* out) {
    for (int p = 0; p < n; p++) vel_at(e, pos[3 * p], pos[3 * p + 1], pos[3 * p + 2], out + 3 * p);
    return 0;
}
AERO_API int aero_slice_z(AeroEngine* e, float z_m, float* out) {
    int k = (int)(z_m / e->dx - 0.5f); if (k < 0) k = 0; if (k >= e->nz) k = e->nz - 1;
    for (int i = 0; i < e->nx; i++) for (int j = 0; j < e->ny; j++)
        vel_at(e, (i + 0.5f) * e->dx, (j + 0.5f) * e->dx, (k + 0.5f) * e->dx, out + 3 * ((size_t)i * e->ny + j));
    return 0;
}
AERO_API int aero_relayout_begin(AeroEngine* e, const uint8_t* solid, float speed, float dir, float z0) {
    free(e->pending); e->pending = (uint8_t*)malloc((size_t)e->nx * e->ny * e->nz);
    memcpy(e->pending, solid, (size_t)e->nx * e->ny * e->nz);
    e->pspeed = speed; e->pdir = dir; e->pz0 = z0; e->polls = 0;
    return 0;
}
AERO_API int aero_relayout_ready(AeroEngine* e) { if (!e->pending) return -1; return ++e->polls >= 3; }
AERO_API int aero_relayout_commit(AeroEngine* e) {
    if (!e->pending) { strcpy(g_err, "no relayout pending"); return -1; }
    memcpy(e->solid, e->pending, (size_t)e->nx * e->ny * e->nz);
    e->speed = e->pspeed; e->dir = e->pdir; e->z0 = e->pz0; free(e->pending); e->pending = NULL;
    return 0;
}
AERO_API int aero_stats(AeroEngine* e, double* mlups, double* step_ms) { *mlups = 1234.5; *step_ms = 0.5; return 0; }
