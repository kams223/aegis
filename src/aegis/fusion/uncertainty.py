"""SF-1 marginal uncertainty declarations; exact, bounded validation, no repair."""
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations, permutations
from math import isfinite
from sys import float_info

from aegis.fusion.contracts import ReferenceFrame

MAX_DIMENSION = 4
MAX_TEXT_BYTES = 1024
UNITS = frozenset(('px', 'm', 'rad', 'm/s', '1'))
Number = int | float
Matrix = tuple[tuple[Number, ...], ...]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    path: str
    explanation: str


class _Fault(ValueError):
    def __init__(self, code, path, explanation):
        self.diagnostic = Diagnostic(code, path, explanation)
        super().__init__(f'{code}: {path}: {explanation}')


def _require(condition, code, path, explanation):
    if not condition:
        raise _Fault(code, path, explanation)


def _text(value, path):
    _require(type(value) is str and 0 < len(value) <= MAX_TEXT_BYTES,
             'TEXT', path, 'Require bounded nonempty text')
    _require(bool(value.strip()) and not any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff for c in value),
             'TEXT', path, 'Require nonblank text without control characters or surrogates')
    _require(len(value.encode('utf-8')) <= MAX_TEXT_BYTES, 'BOUND', path, 'Text exceeds 1024 UTF-8 bytes')


def _number(value, path):
    _require(type(value) in (int, float), 'NUMERIC_TYPE', path, 'Require built-in int or float, not bool')
    _require(type(value) is not int or value.bit_length() <= 1024, 'NUMERIC_RANGE', path, 'Integer exceeds numeric resource bound')
    if type(value) is int:
        # isfinite(int) rounds through float: max-finite + 1 can appear finite.
        _require(abs(value) <= int(float_info.max), 'NUMERIC_RANGE', path,
                 'Integer exceeds the exact finite float magnitude bound')
    else:
        _require(isfinite(value), 'NONFINITE_VALUE', path, 'Require a finite float')


def _frame(value, path):
    _require(type(value) is ReferenceFrame, 'FRAME_MISSING', path, 'Require an explicit ReferenceFrame')
    _text(value.frame_id, path + '.frame_id')


@dataclass(frozen=True, slots=True)
class MeasurementBasis:
    measurement_kind: str
    axes: tuple[str, ...]
    units: tuple[str, ...]
    reference_frame: ReferenceFrame


def _basis(value, path):
    _require(type(value) is MeasurementBasis, 'BASIS', path, 'Require MeasurementBasis')
    _text(value.measurement_kind, path + '.measurement_kind')
    _require(type(value.axes) is tuple and 1 <= len(value.axes) <= MAX_DIMENSION,
             'COVARIANCE_SHAPE', path + '.axes', 'Require 1–4 immutable axes')
    for axis in value.axes:
        _text(axis, path + '.axes')
    _require(len(set(value.axes)) == len(value.axes), 'BASIS', path + '.axes', 'Axes must be distinct')
    _require(type(value.units) is tuple and len(value.units) == len(value.axes),
             'UNITS_MISMATCH', path + '.units', 'One component unit is required per axis')
    _require(all(type(u) is str and u in UNITS for u in value.units),
             'UNITS_MISMATCH', path + '.units', 'Unsupported component unit; no conversion is inferred')
    _frame(value.reference_frame, path + '.reference_frame')


@dataclass(frozen=True, slots=True)
class UncertaintyProvenance:
    model_id: str
    revision: str
    method: str


def _provenance(value):
    _require(type(value) is UncertaintyProvenance, 'UNCERTAINTY_PROVENANCE', 'uncertainty.provenance', 'Require model provenance')
    for name in ('model_id', 'revision', 'method'):
        _text(getattr(value, name), 'uncertainty.provenance.' + name)
    _require(value.method in ('caller_declared', 'calibration', 'synthetic_model'),
             'UNCERTAINTY_PROVENANCE', 'uncertainty.provenance.method', 'Unknown declaration method')


@dataclass(frozen=True, slots=True)
class CovarianceDeclaration:
    """Untrusted declaration. Annotations do not replace validate_covariance."""
    matrix: Matrix
    measurement_basis: MeasurementBasis
    uncertainty_provenance: UncertaintyProvenance


@dataclass(frozen=True, slots=True)
class UnknownUncertainty:
    reason: str


def _determinant(matrix):
    # At most 4! terms. Fraction uses the exact supplied integer/IEEE float values.
    n = len(matrix)
    total = Fraction(0)
    for perm in permutations(range(n)):
        term = Fraction((-1) ** sum(perm[i] > perm[j] for i in range(n) for j in range(i + 1, n)))
        for i, j in enumerate(perm):
            term *= matrix[i][j]
        total += term
    return total


def _rank(matrix, dimension):
    _require(type(matrix) is tuple and len(matrix) == dimension,
             'COVARIANCE_SHAPE', 'uncertainty.matrix', 'Require an immutable square matrix matching the basis')
    for row in matrix:
        _require(type(row) is tuple and len(row) == dimension,
                 'COVARIANCE_SHAPE', 'uncertainty.matrix', 'Require immutable rows with exact dimensions')
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            _number(value, f'uncertainty.matrix[{i}][{j}]')
    exact = tuple(tuple(Fraction(x) for x in row) for row in matrix)
    _require(all(exact[i][j] == exact[j][i] for i in range(dimension) for j in range(i)),
             'COVARIANCE_ASYMMETRIC', 'uncertainty.matrix', 'Exact symmetry is required; no symmetrization is performed')
    rank = 0
    for size in range(1, dimension + 1):
        for indices in combinations(range(dimension), size):
            minor = _determinant(tuple(tuple(exact[i][j] for j in indices) for i in indices))
            _require(minor >= 0, 'COVARIANCE_NOT_PSD', 'uncertainty.matrix',
                     'A principal minor is negative; no tolerance, clipping or jitter is applied')
            if minor > 0:
                rank = size
    return rank


@dataclass(frozen=True, slots=True)
class ValidatedCovariance:
    matrix: Matrix
    measurement_basis: MeasurementBasis
    uncertainty_provenance: UncertaintyProvenance
    rank: int = field(init=False)
    restrictions: tuple[str, ...] = field(init=False)

    def __post_init__(self):
        _basis(self.measurement_basis, 'uncertainty.basis')
        _provenance(self.uncertainty_provenance)
        rank = _rank(self.matrix, len(self.measurement_basis.axes))
        object.__setattr__(self, 'rank', rank)
        object.__setattr__(self, 'restrictions', ('REQUIRES_SINGULAR_MODEL',) if rank < len(self.measurement_basis.axes) else ())


@dataclass(frozen=True, slots=True)
class CovarianceCheck:
    covariance: ValidatedCovariance | None
    diagnostics: tuple[Diagnostic, ...]


def validate_covariance(declaration: CovarianceDeclaration, expected_basis: MeasurementBasis) -> CovarianceCheck:
    """Validate without coercion, copying matrices, numerical repair or I/O.

    All principal minors, not only leading minors, must be nonnegative. For a
    symmetric PSD matrix the largest positive principal-minor size is its rank.
    Unknown uncertainty is handled by admission, never converted to a matrix.
    """
    try:
        _basis(expected_basis, 'expected_basis')
        _require(type(declaration) is CovarianceDeclaration, 'UNCERTAINTY_TYPE', 'uncertainty', 'Require CovarianceDeclaration')
        _basis(declaration.measurement_basis, 'uncertainty.basis')
        actual = declaration.measurement_basis
        _require(actual.reference_frame == expected_basis.reference_frame,
                 'FRAME_MISMATCH', 'uncertainty.basis.reference_frame', 'Covariance frame differs from the measurement frame')
        _require(actual.units == expected_basis.units, 'UNITS_MISMATCH', 'uncertainty.basis.units', 'Covariance component units differ')
        _require(actual.axes == expected_basis.axes and actual.measurement_kind == expected_basis.measurement_kind,
                 'BASIS', 'uncertainty.basis', 'Covariance axes or measurement kind differ')
        return CovarianceCheck(ValidatedCovariance(declaration.matrix, actual, declaration.uncertainty_provenance), ())
    except _Fault as error:
        return CovarianceCheck(None, (error.diagnostic,))
