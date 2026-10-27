"""Analytical checks for exact SF-1 covariance validation."""
from dataclasses import FrozenInstanceError, replace
from math import copysign, inf, nan, nextafter
import pytest
from aegis.fusion.contracts import ReferenceFrame
from aegis.fusion.uncertainty import (
    MeasurementBasis, UncertaintyProvenance, CovarianceDeclaration,
    ValidatedCovariance, validate_covariance,
)


def basis(n=2):
    return MeasurementBasis('analytical', tuple(f'x{i}' for i in range(n)), ('m',) * n, ReferenceFrame('world'))


def declaration(matrix, b=None):
    return CovarianceDeclaration(matrix, b or basis(len(matrix)), UncertaintyProvenance('analytic', '1', 'synthetic_model'))


@pytest.mark.parametrize('matrix,rank', [
    (((4, 0), (0, 9)), 2), (((1, 1), (1, 1)), 1), (((0, 0), (0, 0)), 0),
    (((1, 1, 0), (1, 1, 0), (0, 0, 2)), 2),
    (((1, 2, 3, 4), (2, 4, 6, 8), (3, 6, 9, 12), (4, 8, 12, 16)), 1),
    (((1, 0, 0, 0), (0, 2, 0, 0), (0, 0, 3, 0), (0, 0, 0, 4)), 4),
    (((5e-324,),), 1), (((1 << 1023,),), 1), (((-0.0,),), 0),
])
def test_analytical_psd_rank_and_no_matrix_copy(matrix, rank):
    d = declaration(matrix)
    check = validate_covariance(d, d.measurement_basis)
    assert not check.diagnostics
    c = check.covariance
    assert c.matrix is matrix and c.measurement_basis is d.measurement_basis
    assert c.uncertainty_provenance is d.uncertainty_provenance
    assert c.rank == rank
    assert c.restrictions == (('REQUIRES_SINGULAR_MODEL',) if rank < len(matrix) else ())
    if matrix == ((-0.0,),):
        assert copysign(1, c.matrix[0][0]) == -1
    with pytest.raises(FrozenInstanceError):
        c.rank = 100
    assert check == validate_covariance(d, d.measurement_basis)


@pytest.mark.parametrize('matrix', [
    ((1, 2), (2, 1)), ((0, 1), (1, 0)), ((-1,),),
    ((1, 0, 0), (0, 0, 0), (0, 0, -1)),  # Leading minors alone would miss this.
    ((1., 1.), (1., nextafter(1., 0.))),
    ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 2), (0, 0, 2, 1)),
])
def test_non_psd_is_rejected_without_repair(matrix):
    d = declaration(matrix)
    check = validate_covariance(d, d.measurement_basis)
    assert check.covariance is None
    assert check.diagnostics[0].code == 'COVARIANCE_NOT_PSD'
    with pytest.raises(ValueError):
        ValidatedCovariance(matrix, d.measurement_basis, d.uncertainty_provenance)


def test_adjacent_positive_minor_is_not_rounded_to_zero():
    d = declaration(((1., 1.), (1., nextafter(1., inf))))
    assert validate_covariance(d, d.measurement_basis).covariance.rank == 2


@pytest.mark.parametrize('matrix,code', [
    ([[1, 0], [0, 1]], 'COVARIANCE_SHAPE'), (((1,), (0, 1)), 'COVARIANCE_SHAPE'),
    (((1, 0),), 'COVARIANCE_SHAPE'), (((1, 0), (1e-100, 1)), 'COVARIANCE_ASYMMETRIC'),
    (((True, 0), (0, 1)), 'NUMERIC_TYPE'), (((nan, 0), (0, 1)), 'NONFINITE_VALUE'),
    (((inf, 0), (0, 1)), 'NONFINITE_VALUE'), (((-inf, 0), (0, 1)), 'NONFINITE_VALUE'),
    (((1 << 1024, 0), (0, 1)), 'NUMERIC_RANGE'), ((('1', 0), (0, 1)), 'NUMERIC_TYPE'),
])
def test_malformed_matrix_has_structured_failure(matrix, code):
    check = validate_covariance(declaration(matrix, basis()), basis())
    assert check.covariance is None and check.diagnostics[0].code == code


@pytest.mark.parametrize('n', [0, 5])
def test_dimensions_are_bounded(n):
    b = basis(n)
    assert validate_covariance(declaration((), b), b).diagnostics[0].code == 'COVARIANCE_SHAPE'


@pytest.mark.parametrize('changes,code', [
    ({'units': ('cm', 'cm')}, 'UNITS_MISMATCH'), ({'units': ('rad', 'rad')}, 'UNITS_MISMATCH'),
    ({'axes': ('y', 'x')}, 'BASIS'), ({'axes': ('x', 'x')}, 'BASIS'),
    ({'reference_frame': None}, 'FRAME_MISSING'),
    ({'reference_frame': ReferenceFrame('other')}, 'FRAME_MISMATCH'),
    ({'measurement_kind': 'different'}, 'BASIS'),
])
def test_covariance_basis_must_match(changes, code):
    d = declaration(((1, 0), (0, 1)))
    changed = replace(d, measurement_basis=replace(d.measurement_basis, **changes))
    assert validate_covariance(changed, basis()).diagnostics[0].code == code


def test_provenance_is_required_and_unknown_is_not_a_matrix():
    d = declaration(((1, 0), (0, 1)))
    assert validate_covariance(replace(d, uncertainty_provenance=None), basis()).diagnostics[0].code == 'UNCERTAINTY_PROVENANCE'
    assert validate_covariance(None, basis()).diagnostics[0].code == 'UNCERTAINTY_TYPE'


@pytest.mark.parametrize('offset', [1, 1 << 969])
def test_integer_range_is_checked_before_rounding_to_float(offset):
    from sys import float_info
    largest = int(float_info.max)
    assert validate_covariance(declaration(((largest,),)), basis(1)).covariance.rank == 1
    check = validate_covariance(declaration(((largest + offset,),)), basis(1))
    assert check.covariance is None
    assert check.diagnostics[0].code == 'NUMERIC_RANGE'


def _schur_psd_and_rank(matrix):
    """Independent exact elimination oracle, rather than principal minors."""
    from fractions import Fraction
    a = [list(map(Fraction, row)) for row in matrix]
    rank = 0
    for i in range(len(a)):
        pivot = a[i][i]
        if pivot < 0:
            return False, None
        if pivot == 0:
            if any(a[i][j] != 0 for j in range(i + 1, len(a))):
                return False, None
            continue
        rank += 1
        for j in range(i + 1, len(a)):
            for k in range(i + 1, len(a)):
                a[j][k] -= a[j][i] * a[i][k] / pivot
    return True, rank


def test_exhaustive_small_symmetric_matrices_against_independent_schur_oracle():
    from itertools import product
    for n, values in ((2, range(-2, 3)), (3, range(-1, 2))):
        positions = [(i, j) for i in range(n) for j in range(i, n)]
        for entries in product(values, repeat=len(positions)):
            matrix = [[0] * n for _ in range(n)]
            for (i, j), value in zip(positions, entries):
                matrix[i][j] = matrix[j][i] = value
            matrix = tuple(map(tuple, matrix))
            psd, rank = _schur_psd_and_rank(matrix)
            check = validate_covariance(declaration(matrix), basis(n))
            assert (check.covariance is not None) == psd, matrix
            if psd:
                assert check.covariance.rank == rank, matrix


@pytest.mark.parametrize('matrix', [
    ((0, 0, 0, 0), (0, 1, 2, 0), (0, 2, 4, 0), (0, 0, 0, 3)),
    ((1, 0, 1, 1), (0, 1, 1, -1), (1, 1, 2, 0), (1, -1, 0, 2)),
    ((1, 2, 0, 1), (2, 5, 0, 1), (0, 0, 3, 0), (1, 1, 0, 2)),
])
def test_four_dimensional_rank_with_nonleading_and_dependent_rows(matrix):
    psd, rank = _schur_psd_and_rank(matrix)
    assert psd
    check = validate_covariance(declaration(matrix), basis(4))
    assert check.covariance is not None and check.covariance.rank == rank


def test_extreme_finite_float_matrices_do_not_overflow_or_underflow_determinants():
    from sys import float_info
    largest = float_info.max
    tiny = float.fromhex('0x0.0000000000001p-1022')
    for matrix, rank in ((tuple((largest,) * 4 for _ in range(4)), 1),
                         (((largest, 0., 0., 0.), (0., tiny, 0., 0.),
                           (0., 0., largest, 0.), (0., 0., 0., tiny)), 4)):
        check = validate_covariance(declaration(matrix), basis(4))
        assert check.covariance is not None and check.covariance.rank == rank
        assert check.covariance.matrix is matrix
