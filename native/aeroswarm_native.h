/* AeroSwarm native wind engine - C ABI contract (version 1).
 *
 * The team's own CUDA engine exports these functions from a shared library
 * (aeroswarm_native.dll / libaeroswarm_native.so). engine/wind/native.py loads it with ctypes and presents it
 * as the fourth WindSource adapter ("native"). Nothing else in AeroSwarm knows the engine exists.
 *
 * Conventions
 *   - SI units at this boundary (metres, seconds, m/s); lattice units stay inside the engine.
 *   - Coordinates: x east, y north, z up, origin at the south-west corner; cell (i,j,k) is centred at
 *     ((i+.5)dx, (j+.5)dx, (k+.5)dx).
 *   - Arrays are contiguous host memory, row-major [nx][ny][nz] (k fastest):  index = (i*ny + j)*nz + k.
 *     Vector fields are float32 with the 3 components innermost: [..][3].
 *   - Every function returns 0 on success, a negative error code otherwise (aero_last_error() has the text).
 *   - Single-threaded use from the Python service thread; no function is called concurrently.
 */
#ifndef AEROSWARM_NATIVE_H
#define AEROSWARM_NATIVE_H
#include <stdint.h>

#ifdef _WIN32
#define AERO_API __declspec(dllexport)
#else
#define AERO_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif

typedef struct AeroEngine AeroEngine;

#define AERO_ABI_VERSION 1

/* Must return AERO_ABI_VERSION; the Python adapter refuses any other value. */
AERO_API int aero_abi_version(void);

/* Create an engine for an nx*ny*nz grid of spacing dx_m. dt_s is the simulation step the service will pass to
 * aero_step (the engine converts to its own lattice steps). Returns NULL on failure. */
AERO_API AeroEngine* aero_create(int nx, int ny, int nz, float dx_m, float dt_s);
AERO_API void aero_destroy(AeroEngine*);

/* solid: uint8 [nx][ny][nz], 1 = building cell. Inflow: log-law U(z) = speed * ln(z/z0)/ln(10/z0) blowing toward
 * direction_deg (CCW from +x). Resets the flow to its initial state. */
AERO_API int aero_reset(AeroEngine*, const uint8_t* solid, float speed_ms, float direction_deg, float roughness_m);

/* Advance n simulation steps of dt_s. */
AERO_API int aero_step(AeroEngine*, int n);

/* Trilinear velocity at n points: pos float32 [n][3] metres -> out_vel float32 [n][3] m/s. Zero inside solids. */
AERO_API int aero_sample(AeroEngine*, const float* pos, int n, float* out_vel);

/* Velocity on the grid layer nearest z_m: out float32 [nx][ny][3]. */
AERO_API int aero_slice_z(AeroEngine*, float z_m, float* out);

/* Live building edits: build the new geometry/inflow in the background (the old wind keeps running through
 * aero_step), poll until ready, then commit at a step boundary. */
AERO_API int aero_relayout_begin(AeroEngine*, const uint8_t* solid, float speed_ms, float direction_deg, float roughness_m);
AERO_API int aero_relayout_ready(AeroEngine*);          /* 1 = ready, 0 = still settling, <0 = error */
AERO_API int aero_relayout_commit(AeroEngine*);

/* Performance counters of the last steps. */
AERO_API int aero_stats(AeroEngine*, double* mlups, double* step_ms);

AERO_API const char* aero_last_error(void);

#ifdef __cplusplus
}
#endif
#endif
