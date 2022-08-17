from rdkit import Chem
import os
import shutil
import subprocess
import traceback

import numpy as np

from .log_parser import XtbLog, G16Log
from .file_parser import mol2xyz, xyz2com, write_mol_to_sdf, write_mols_to_sdf


def semiempirical_opt(mol_id, xtb_path, rdmc_path, g16_path, level_of_theory, n_procs, job_ram, base_charge, mult, method, logger):
    sdf = mol_id + ".sdf"

    work_dir = os.getcwd()

    mols = Chem.SDMolSupplier(sdf, removeHs=False, sanitize=False)
    os.remove(sdf)
    conf_mols_ids_ens = []
    for conf_ind, mol in enumerate(mols):

        scratch_dir = f"{mol_id}_{conf_ind}_{level_of_theory}"
        try:
            shutil.rmtree(scratch_dir)
        except:
            pass
        os.makedirs(scratch_dir)
        os.chdir(scratch_dir)

        xyz = mol2xyz(mol)

        g16_command = os.path.join(g16_path, 'g16')

        if method == "GFN2-XTB":
            head = '%nprocshared={}\n%mem={}mb\n{}\nexternal=\"{}/rdmc/external/xtb_tools/xtb_gaussian.pl --gfn 2 -P\"\n'.format(n_procs, job_ram, level_of_theory, rdmc_path)
        else:
            head = '%nprocshared={}\n%mem={}mb\n{} {}\n'.format(n_procs, job_ram, level_of_theory, method)

        comfile = f"{mol_id}_{conf_ind}.gjf"
        xyz2com(xyz, head=head, comfile=comfile, charge=base_charge, mult=mult, footer='\n')

        logfile = f"{mol_id}_{conf_ind}.log"
        outfile = f"{mol_id}_{conf_ind}.out"

        with open(outfile, 'w') as out:
            subprocess.run('{} < {} >> {}'.format(g16_command, comfile, logfile), shell=True, stdout=out, stderr=out)

        log = G16Log(logfile)
        if log.termination and np.min(log.har_frequencies) > 0:
            mol.SetProp('ConfId', str(conf_ind)) #convert to kcal/mol
            mol.SetProp('ConfEnergies', str(log.E*627.5) + ' kcal/mol') #convert to kcal/mol
            conf = mol.GetConformer()
            for i in range(mol.GetNumAtoms()):
                conf.SetAtomPosition(i, log.Coords[i,:])
            conf_mols_ids_ens.append((mol, log.E))
            shutil.copy(logfile, os.path.join(work_dir, logfile))
            logger.info(f'optimization of conformer {conf_ind} for {mol_id} completed.')
            os.chdir(work_dir)
            shutil.rmtree(scratch_dir)
        else:
            if not log.termination:
                logger.error(f'optimization of conformer {conf_ind} for {mol_id} failed due to error termination.')
            elif not (np.min(log.har_frequencies) > 0.0):
                logger.error(f'optimization of conformer {conf_ind} for {mol_id} failed due to negative frequency.')
            os.chdir(work_dir)

    if conf_mols_ids_ens:
        conf_mols_ids_ens.sort(key=lambda x: x[1])
        opt_mols = [mol for mol, en in conf_mols_ids_ens]
        write_mols_to_sdf(opt_mols, f'{mol_id}_confs_opt.sdf')
        write_mol_to_sdf(opt_mols[0], f'{mol_id}_opt.sdf')
    else:
        raise RuntimeError(f'all optimization for {mol_id} failed')

def xtb_status(folder, molid):

    try:
        log = XtbLog(os.path.join(folder,'{}_freq.log'.format(molid)))
    except:
        raise RuntimeError(f'xtb log file not found for {molid}')

    if log.termination:
        peaks = log.wavenum
        if np.min(peaks) < 0:
            raise RuntimeError('imaginary frequency found for {}'.format(molid))
        else:
            return '{}_opt.sdf'.format(molid)
    else:
        raise RuntimeError('xtb optimization did not finish for {}'.format(molid))