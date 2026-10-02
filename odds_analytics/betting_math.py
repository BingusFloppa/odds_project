from __future__ import annotations

import hashlib

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


def resolve_asian_total(total_goals, line, odds, is_over):
    if line % 1 == 0:
        if total_goals == line:
            return 0.0
        if (total_goals > line and is_over) or (total_goals < line and not is_over):
            return odds - 1.0
        return -1.0
    if line % 0.5 == 0:
        if (total_goals > line and is_over) or (total_goals < line and not is_over):
            return odds - 1.0
        return -1.0
    line1, line2 = line - 0.25, line + 0.25
    return 0.5 * (
        resolve_asian_total(total_goals, line1, odds, is_over)
        + resolve_asian_total(total_goals, line2, odds, is_over)
    )


def resolve_asian_hcap(diff, line, odds):
    if line % 1 == 0:
        if diff + line == 0:
            return 0.0
        if diff + line > 0:
            return odds - 1.0
        return -1.0
    if line % 0.5 == 0:
        return odds - 1.0 if diff + line > 0 else -1.0
    line1, line2 = line - 0.25, line + 0.25
    return 0.5 * (
        resolve_asian_hcap(diff, line1, odds)
        + resolve_asian_hcap(diff, line2, odds)
    )


def biv_poisson_matrix(l1, l2, l3, max_goals=10):
    m1 = poisson.pmf(np.arange(max_goals), l1)
    m2 = poisson.pmf(np.arange(max_goals), l2)
    independent = np.outer(m1, m2)
    if l3 <= 0.001:
        return independent / np.sum(independent)

    matrix = np.zeros((max_goals, max_goals))
    for k in range(max_goals):
        p_l3 = poisson.pmf(k, l3)
        if p_l3 < 1e-7:
            continue
        shifted = np.zeros((max_goals, max_goals))
        shifted[k:, k:] = independent[: max_goals - k, : max_goals - k]
        matrix += p_l3 * shifted
    return matrix / np.sum(matrix)


def calc_asian_prob(matrix, line, is_total=True):
    idx = (
        np.arange(10)[:, None] + np.arange(10)[None, :]
        if is_total
        else np.arange(10)[:, None] - np.arange(10)[None, :]
    )
    if line % 1 == 0:
        p_push = np.sum(matrix[idx == line])
        p1 = np.sum(matrix[idx > line])
        p2 = np.sum(matrix[idx < line])
        denom = 1 - p_push
        return (p1 / denom, p2 / denom) if denom > 0 else (0, 0)
    if line % 0.5 == 0:
        return np.sum(matrix[idx > line]), np.sum(matrix[idx < line])

    l1, l2 = line - 0.25, line + 0.25
    p_push1 = np.sum(matrix[idx == l1])
    p_push2 = np.sum(matrix[idx == l2])
    p1 = 0.5 * np.sum(matrix[idx > l1]) + 0.5 * np.sum(matrix[idx > l2])
    p2 = 0.5 * np.sum(matrix[idx < l1]) + 0.5 * np.sum(matrix[idx < l2])
    denom = 1 - 0.5 * (p_push1 + p_push2)
    return (p1 / denom, p2 / denom) if denom > 0 else (0, 0)


def calculate_bivariate_params(k1, kx, k2, tl, oo, ou, hl, oh1, oh2):
    target_1x2 = np.array([1 / k1, 1 / kx, 1 / k2], dtype=float)
    target_1x2 /= np.sum(target_1x2)
    target_ou = (
        np.array([1 / oo, 1 / ou]) / (1 / oo + 1 / ou)
        if tl and oo and ou
        else None
    )
    target_ah = (
        np.array([1 / oh1, 1 / oh2]) / (1 / oh1 + 1 / oh2)
        if hl and oh1 and oh2
        else None
    )

    def loss_func(params):
        l1, l2, l3 = params
        if l1 <= 0 or l2 <= 0 or l3 < 0:
            return 1e6
        matrix = biv_poisson_matrix(l1, l2, l3)
        p_home = np.sum(np.tril(matrix, -1))
        p_draw = np.sum(np.diag(matrix))
        p_away = np.sum(np.triu(matrix, 1))
        loss = (
            (p_home - target_1x2[0]) ** 2
            + (p_draw - target_1x2[1]) ** 2
            + (p_away - target_1x2[2]) ** 2
        )
        if target_ou is not None:
            po, pu = calc_asian_prob(matrix, tl, is_total=True)
            loss += (po - target_ou[0]) ** 2 + (pu - target_ou[1]) ** 2
        if target_ah is not None:
            ph1, ph2 = calc_asian_prob(matrix, -hl, is_total=False)
            loss += (ph1 - target_ah[0]) ** 2 + (ph2 - target_ah[1]) ** 2
        return loss

    result = minimize(
        loss_func,
        [1.0, 1.0, 0.1],
        bounds=[(0.01, 5), (0.01, 5), (0.0, 2)],
    )
    return (
        float(result.x[0]),
        float(result.x[1]),
        float(result.x[2]),
        float(result.fun),
    )


def get_true_prob(matrix, market, line_val=None):
    if market == "1":
        return np.sum(np.tril(matrix, -1))
    if market == "X":
        return np.sum(np.diag(matrix))
    if market == "2":
        return np.sum(np.triu(matrix, 1))

    if market in {"Over", "Under"}:
        idx = np.arange(10)[:, None] + np.arange(10)[None, :]
        if line_val % 1 == 0:
            p_push = np.sum(matrix[idx == line_val])
            p_win = (
                np.sum(matrix[idx > line_val])
                if market == "Over"
                else np.sum(matrix[idx < line_val])
            )
            return p_win / (1 - p_push) if (1 - p_push) > 0 else 0
        if line_val % 0.5 == 0:
            return (
                np.sum(matrix[idx > line_val])
                if market == "Over"
                else np.sum(matrix[idx < line_val])
            )

        l1, l2 = line_val - 0.25, line_val + 0.25
        p_push1 = np.sum(matrix[idx == l1])
        p_push2 = np.sum(matrix[idx == l2])
        p_win1 = (
            np.sum(matrix[idx > l1])
            if market == "Over"
            else np.sum(matrix[idx < l1])
        )
        p_win2 = (
            np.sum(matrix[idx > l2])
            if market == "Over"
            else np.sum(matrix[idx < l2])
        )
        denom = 1 - 0.5 * (p_push1 + p_push2)
        return (0.5 * p_win1 + 0.5 * p_win2) / denom if denom > 0 else 0

    if market in {"H1", "H2"}:
        diff = np.arange(10)[:, None] - np.arange(10)[None, :]
        if market == "H2":
            diff = -diff
        if line_val % 1 == 0:
            p_push = np.sum(matrix[diff == -line_val])
            p_win = np.sum(matrix[diff > -line_val])
            return p_win / (1 - p_push) if (1 - p_push) > 0 else 0
        if line_val % 0.5 == 0:
            return np.sum(matrix[diff > -line_val])

        l1, l2 = line_val - 0.25, line_val + 0.25
        p_push1 = np.sum(matrix[diff == -l1])
        p_push2 = np.sum(matrix[diff == -l2])
        p_win1 = np.sum(matrix[diff > -l1])
        p_win2 = np.sum(matrix[diff > -l2])
        denom = 1 - 0.5 * (p_push1 + p_push2)
        return (0.5 * p_win1 + 0.5 * p_win2) / denom if denom > 0 else 0
    return 0.0


def cache_key(*values) -> str:
    normalized = []
    for value in values:
        if value is None:
            normalized.append("None")
        else:
            try:
                normalized.append(f"{float(value):.2f}")
            except (TypeError, ValueError):
                normalized.append(str(value))
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()
