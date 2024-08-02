"""Helper methods of phonopy loader."""

# Copyright (C) 2018 Atsushi Togo
# All rights reserved.
#
# This file is part of phonopy.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in
#   the documentation and/or other materials provided with the
#   distribution.
#
# * Neither the name of the phonopy project nor the names of its
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import pathlib
from typing import Optional

import numpy as np

from phonopy import Phonopy
from phonopy.exception import ForcesetsNotFoundError
from phonopy.file_IO import (
    parse_BORN,
    parse_FORCE_CONSTANTS,
    parse_FORCE_SETS,
    read_force_constants_hdf5,
)
from phonopy.harmonic.force_constants import (
    compact_fc_to_full_fc,
    full_fc_to_compact_fc,
)
from phonopy.interface.calculator import (
    get_force_constant_conversion_factor,
    read_crystal_structure,
)
from phonopy.structure.atoms import PhonopyAtoms
from phonopy.structure.cells import get_primitive_matrix


def get_cell_settings(
    supercell_matrix=None,
    primitive_matrix=None,
    unitcell=None,
    supercell=None,
    unitcell_filename=None,
    supercell_filename=None,
    calculator=None,
    symprec=1e-5,
    log_level=0,
):
    """Return crystal structures."""
    optional_structure_info = None
    if primitive_matrix is None or (
        isinstance(primitive_matrix, str) and primitive_matrix == "auto"
    ):
        pmat = "auto"
    else:
        pmat = primitive_matrix

    if unitcell_filename is not None:
        cell, optional_structure_info = _read_crystal_structure(
            filename=unitcell_filename, interface_mode=calculator
        )
        smat = supercell_matrix
        if log_level:
            print(
                'Unit cell structure was read from "%s".' % optional_structure_info[0]
            )
    elif supercell_filename is not None:
        cell, optional_structure_info = read_crystal_structure(
            filename=supercell_filename, interface_mode=calculator
        )
        smat = np.eye(3, dtype="intc", order="C")
        if log_level:
            print(
                'Supercell structure was read from "%s".' % optional_structure_info[0]
            )
    elif unitcell is not None:
        cell = PhonopyAtoms(atoms=unitcell)
        smat = supercell_matrix
    elif supercell is not None:
        cell = PhonopyAtoms(atoms=supercell)
        smat = np.eye(3, dtype="intc", order="C")
    else:
        raise RuntimeError("Cell has to be specified.")

    if optional_structure_info is not None and cell is None:
        filename = optional_structure_info[0]
        msg = "'%s' could not be found." % filename
        raise FileNotFoundError(msg)

    pmat = get_primitive_matrix(pmat, symprec=symprec)

    return cell, smat, pmat


def get_nac_params(
    primitive=None,
    nac_params=None,
    born_filename=None,
    is_nac=True,
    nac_factor=None,
    log_level=0,
):
    """Look for and return NAC parameters."""
    if born_filename is not None:
        _nac_params = parse_BORN(primitive, filename=born_filename)
        if log_level:
            print('NAC parameters were read from "%s".' % born_filename)
    elif nac_params is not None:  # nac_params input or phonopy_yaml.nac_params
        _nac_params = nac_params
    elif is_nac and pathlib.Path("BORN").exists():
        _nac_params = parse_BORN(primitive, filename="BORN")
        if log_level:
            print('NAC params were read from "BORN".')
    else:
        _nac_params = None

    if _nac_params is not None:
        if "factor" not in _nac_params or _nac_params["factor"] is None:
            _nac_params["factor"] = nac_factor

    return _nac_params


def read_force_constants_from_hdf5(
    filename="force_constants.hdf5", p2s_map=None, calculator=None
):
    """Convert force constants physical unit.

    Each calculator interface has own default force constants physical unit.
    This method reads 'physical_unit' in force constants hdf5 file and
    if this is different from the one for 'calculator', the force constants
    are converted to have the physical unit of the calculator.

    Note
    ----
    This method is also used from phonopy script.

    """
    fc, fc_unit = read_force_constants_hdf5(
        filename=filename, p2s_map=p2s_map, return_physical_unit=True
    )
    if fc_unit is None:
        return fc
    else:
        factor = get_force_constant_conversion_factor(fc_unit, calculator)
        return fc * factor


def set_dataset_and_force_constants(
    phonon: Phonopy,
    dataset: dict,
    fc: Optional[np.ndarray],  # From phonopy_yaml
    force_constants_filename: Optional[str] = None,
    force_sets_filename: Optional[str] = None,
    fc_calculator: Optional[str] = None,
    fc_calculator_options: Optional[str] = None,
    produce_fc: bool = True,
    symmetrize_fc: bool = True,
    is_compact_fc: bool = True,
    use_pypolymlp: bool = False,
    log_level: int = 0,
):
    """Set displacement-force dataset and force constants."""
    natom = len(phonon.supercell)

    # dataset and fc are those obtained from phonopy_yaml unless None.
    if dataset is not None:
        if use_pypolymlp:
            phonon.mlp_dataset = dataset
        else:
            phonon.dataset = dataset
    if fc is not None:
        phonon.force_constants = fc

    _fc = None
    _dataset = None
    if force_constants_filename is not None:
        _fc = _read_force_constants_file(
            phonon,
            force_constants_filename,
            is_compact_fc=is_compact_fc,
            log_level=log_level,
        )
        _force_constants_filename = force_constants_filename
    elif force_sets_filename is not None:
        _dataset = parse_FORCE_SETS(natom=natom, filename=force_sets_filename)
        _force_sets_filename = force_sets_filename
    elif phonon.forces is None and phonon.force_constants is None:
        # unless provided these from phonopy_yaml.
        if pathlib.Path("FORCE_CONSTANTS").exists():
            _fc = _read_force_constants_file(
                phonon,
                "FORCE_CONSTANTS",
                is_compact_fc=is_compact_fc,
                log_level=log_level,
            )
            _force_constants_filename = "FORCE_CONSTANTS"
        elif pathlib.Path("force_constants.hdf5").exists():
            _fc = _read_force_constants_file(
                phonon,
                "force_constants.hdf5",
                is_compact_fc=is_compact_fc,
                log_level=log_level,
            )
            _force_constants_filename = "force_constants.hdf5"
        elif pathlib.Path("FORCE_SETS").exists():
            _dataset = parse_FORCE_SETS(natom=natom)
            _force_sets_filename = "FORCE_SETS"

    if _fc is not None:
        phonon.force_constants = _fc
        if log_level:
            print('Force constants were read from "%s".' % _force_constants_filename)

    if phonon.force_constants is None:
        # Overwrite dataset
        if _dataset is not None:
            if phonon.dataset is None:
                is_overwritten = False
            else:
                is_overwritten = (
                    "first_atoms" in phonon.dataset or "displacements" in phonon.dataset
                )
            phonon.dataset = _dataset
            if log_level:
                print('Force sets were read from "%s".' % _force_sets_filename)
                if is_overwritten:
                    print(
                        f'Displacements were overwritten by "{_force_sets_filename}".'
                    )

        if produce_fc:
            _produce_force_constants(
                phonon,
                fc_calculator,
                fc_calculator_options,
                symmetrize_fc,
                is_compact_fc,
                log_level,
            )


def _read_force_constants_file(
    phonon: Phonopy, force_constants_filename, is_compact_fc=True, log_level=0
):
    dot_split = force_constants_filename.split(".")
    p2s_map = phonon.primitive.p2s_map
    if len(dot_split) > 1 and dot_split[-1] == "hdf5":
        _fc = read_force_constants_from_hdf5(
            filename=force_constants_filename,
            p2s_map=p2s_map,
            calculator=phonon.calculator,
        )
    else:
        _fc = parse_FORCE_CONSTANTS(filename=force_constants_filename, p2s_map=p2s_map)

    if is_compact_fc and _fc.shape[0] == _fc.shape[1]:
        _fc = full_fc_to_compact_fc(phonon, _fc, log_level=log_level)
    elif not is_compact_fc and _fc.shape[0] != _fc.shape[1]:
        _fc = compact_fc_to_full_fc(phonon, _fc, log_level=log_level)

    return _fc


def _produce_force_constants(
    phonon: Phonopy,
    fc_calculator: Optional[str],
    fc_calculator_options: Optional[str],
    symmetrize_fc: bool,
    is_compact_fc: bool,
    log_level: int,
):
    try:
        phonon.produce_force_constants(
            calculate_full_force_constants=(not is_compact_fc),
            fc_calculator=fc_calculator,
            fc_calculator_options=fc_calculator_options,
        )
        if symmetrize_fc:
            phonon.symmetrize_force_constants(show_drift=(log_level > 0))
            if log_level:
                print("Force constants were symmetrized.")
    except ForcesetsNotFoundError:
        if log_level:
            print("Force constants not produced due to force set not found.")


def _read_crystal_structure(filename=None, interface_mode=None):
    try:
        return read_crystal_structure(filename=filename, interface_mode=interface_mode)
    except FileNotFoundError:
        raise
    except Exception as exc:
        msg = [
            "============================ phonopy.load " "============================",
            "  Reading crystal structure file failed in phonopy.load.",
            "  Maybe phonopy.load(..., calculator='<calculator name>') " "expected?",
            "============================ phonopy.load " "============================",
        ]
        raise RuntimeError("\n".join(msg)) from exc
