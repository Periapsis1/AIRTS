# cython: boundscheck=False, wraparound=False, cdivision=True
"""Cython collision pass: spatial hash + resolution, all in C.

Replaces the Python QuadField query + per-pair math loop with a single
C-level function. The only Python object access is reading/writing
unit attributes at the start/end.
"""
from libc.math cimport sqrt
from libc.stdlib cimport malloc, free, calloc
from libc.string cimport memcpy


def collision_pass(list alive_units):
    """Complete spatial-hash collision pass.

    Builds a temporary grid from unit positions, finds overlapping pairs,
    and resolves them — entirely in C except for the initial attribute
    reads and final position writebacks.

    Modifies unit.x / unit.y in place for mobile units.
    """
    cdef int n = <int>len(alive_units)
    if n < 2:
        return

    # -- Extract unit data into C arrays --
    cdef double* px = <double*>malloc(n * sizeof(double))
    cdef double* py = <double*>malloc(n * sizeof(double))
    cdef double* rad = <double*>malloc(n * sizeof(double))
    cdef char* bld = <char*>malloc(n * sizeof(char))
    if not px or not py or not rad or not bld:
        free(px); free(py); free(rad); free(bld)
        return

    cdef int i
    cdef double max_rad = 0.0
    cdef object u

    for i in range(n):
        u = alive_units[i]
        px[i] = <double>u.x
        py[i] = <double>u.y
        rad[i] = <double>u.radius
        bld[i] = 1 if u.is_building else 0
        if rad[i] > max_rad:
            max_rad = rad[i]

    if max_rad < 0.5:
        max_rad = 0.5

    # -- Build spatial hash grid --
    cdef double cell_size = max_rad * 2.0
    cdef double inv_cell = 1.0 / cell_size

    # Bounding box (with margin)
    cdef double min_x = px[0], max_x = px[0]
    cdef double min_y = py[0], max_y = py[0]
    for i in range(1, n):
        if px[i] < min_x: min_x = px[i]
        if px[i] > max_x: max_x = px[i]
        if py[i] < min_y: min_y = py[i]
        if py[i] > max_y: max_y = py[i]
    min_x -= max_rad
    min_y -= max_rad

    cdef int ncols = <int>((max_x - min_x) * inv_cell) + 2
    cdef int nrows = <int>((max_y - min_y) * inv_cell) + 2
    cdef int num_cells = ncols * nrows

    # Counting sort: assign each unit to a cell, then sort by cell
    cdef int* cell_id = <int*>malloc(n * sizeof(int))
    cdef int* cell_count = <int*>calloc(num_cells, sizeof(int))
    cdef int* cell_start = <int*>malloc(num_cells * sizeof(int))
    cdef int* sorted_idx = <int*>malloc(n * sizeof(int))
    cdef int* fill_pos = <int*>malloc(num_cells * sizeof(int))
    if not cell_id or not cell_count or not cell_start or not sorted_idx or not fill_pos:
        free(px); free(py); free(rad); free(bld)
        free(cell_id); free(cell_count); free(cell_start); free(sorted_idx); free(fill_pos)
        return

    cdef int cx, cy, ci
    for i in range(n):
        cx = <int>((px[i] - min_x) * inv_cell)
        cy = <int>((py[i] - min_y) * inv_cell)
        if cx < 0: cx = 0
        if cx >= ncols: cx = ncols - 1
        if cy < 0: cy = 0
        if cy >= nrows: cy = nrows - 1
        ci = cy * ncols + cx
        cell_id[i] = ci
        cell_count[ci] += 1

    # Prefix sum → cell_start
    cell_start[0] = 0
    for i in range(1, num_cells):
        cell_start[i] = cell_start[i - 1] + cell_count[i - 1]
    memcpy(fill_pos, cell_start, num_cells * sizeof(int))

    # Place units into sorted array
    for i in range(n):
        ci = cell_id[i]
        sorted_idx[fill_pos[ci]] = i
        fill_pos[ci] += 1

    # -- Resolve collisions --
    cdef int a, b, ai, bi, k
    cdef int nx_c, ny_c, ni
    cdef double dx, dy, dist_sq, min_dist, dist, overlap, nvx, nvy, half
    cdef int a_bld, b_bld
    cdef int s1, e1, s2, e2

    # Neighbor offsets: (1,0), (-1,1), (0,1), (1,1)
    # Each cell pair is visited exactly once
    cdef int offsets_x[4]
    cdef int offsets_y[4]
    offsets_x[0] = 1;  offsets_y[0] = 0
    offsets_x[1] = -1; offsets_y[1] = 1
    offsets_x[2] = 0;  offsets_y[2] = 1
    offsets_x[3] = 1;  offsets_y[3] = 1

    for cy in range(nrows):
        for cx in range(ncols):
            ci = cy * ncols + cx
            s1 = cell_start[ci]
            e1 = s1 + cell_count[ci]
            if s1 == e1:
                continue

            # Same-cell pairs
            for a in range(s1, e1):
                ai = sorted_idx[a]
                for b in range(a + 1, e1):
                    bi = sorted_idx[b]
                    a_bld = bld[ai]
                    b_bld = bld[bi]
                    if a_bld and b_bld:
                        continue

                    dx = px[bi] - px[ai]
                    dy = py[bi] - py[ai]
                    dist_sq = dx * dx + dy * dy
                    min_dist = rad[ai] + rad[bi]
                    if dist_sq >= min_dist * min_dist:
                        continue

                    if dist_sq < 1e-24:
                        dist_sq = 1e-24
                    dist = sqrt(dist_sq)
                    overlap = min_dist - dist
                    nvx = dx / dist
                    nvy = dy / dist

                    if b_bld:
                        px[ai] = px[ai] - nvx * overlap
                        py[ai] = py[ai] - nvy * overlap
                    elif a_bld:
                        px[bi] = px[bi] + nvx * overlap
                        py[bi] = py[bi] + nvy * overlap
                    else:
                        half = overlap * 0.5
                        px[ai] = px[ai] - nvx * half
                        py[ai] = py[ai] - nvy * half
                        px[bi] = px[bi] + nvx * half
                        py[bi] = py[bi] + nvy * half

            # Cross-cell pairs (4 neighbor offsets)
            for k in range(4):
                nx_c = cx + offsets_x[k]
                ny_c = cy + offsets_y[k]
                if nx_c < 0 or nx_c >= ncols or ny_c < 0 or ny_c >= nrows:
                    continue
                ni = ny_c * ncols + nx_c
                s2 = cell_start[ni]
                e2 = s2 + cell_count[ni]
                if s2 == e2:
                    continue

                for a in range(s1, e1):
                    ai = sorted_idx[a]
                    for b in range(s2, e2):
                        bi = sorted_idx[b]
                        a_bld = bld[ai]
                        b_bld = bld[bi]
                        if a_bld and b_bld:
                            continue

                        dx = px[bi] - px[ai]
                        dy = py[bi] - py[ai]
                        dist_sq = dx * dx + dy * dy
                        min_dist = rad[ai] + rad[bi]
                        if dist_sq >= min_dist * min_dist:
                            continue

                        if dist_sq < 1e-24:
                            dist_sq = 1e-24
                        dist = sqrt(dist_sq)
                        overlap = min_dist - dist
                        nvx = dx / dist
                        nvy = dy / dist

                        if b_bld:
                            px[ai] = px[ai] - nvx * overlap
                            py[ai] = py[ai] - nvy * overlap
                        elif a_bld:
                            px[bi] = px[bi] + nvx * overlap
                            py[bi] = py[bi] + nvy * overlap
                        else:
                            half = overlap * 0.5
                            px[ai] = px[ai] - nvx * half
                            py[ai] = py[ai] - nvy * half
                            px[bi] = px[bi] + nvx * half
                            py[bi] = py[bi] + nvy * half

    # -- Write back positions to Python units --
    for i in range(n):
        if not bld[i]:
            u = alive_units[i]
            u.x = px[i]
            u.y = py[i]

    free(px); free(py); free(rad); free(bld)
    free(cell_id); free(cell_count); free(cell_start); free(sorted_idx); free(fill_pos)
