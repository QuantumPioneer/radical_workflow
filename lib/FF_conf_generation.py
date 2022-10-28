#!/usr/bin/python
from __future__ import print_function, absolute_import
import shutil
import subprocess

from multiprocessing import Process, Manager

from rdkit import Chem
from rdkit.Chem import AllChem
from concurrent import futures
from .log_parser import XtbLog
from .file_parser import write_mol_to_sdf, load_sdf
import os
import traceback

# algorithm to generate nc conformations
def _genConf(smi, mol_id, XTB_path, conf_search_FF, max_n_conf, max_try, rms, E_cutoff_fraction, rmspost, n_lowest_E_confs_to_save, job_id, task_id, scratch_dir, save_dir, input_dir):
    mol = Chem.MolFromSmiles(smi)
    mol = Chem.AddHs(mol)
    nr = int(AllChem.CalcNumRotatableBonds(mol))

    tnr = 3**nr
    num_conf_attempts = tnr if tnr < max_n_conf else max_n_conf
    ids = AllChem.EmbedMultipleConfs(mol, numConfs=num_conf_attempts, maxAttempts=max_try, pruneRmsThresh=rms,
                                   randomSeed=1, useExpTorsionAnglePrefs=True, useBasicKnowledge=True)

    if len(ids) == 0:
        ids = AllChem.EmbedMultipleConfs(mol, numConfs=num_conf_attempts, maxAttempts=max_try, pruneRmsThresh=rms,
                                   randomSeed=1, useExpTorsionAnglePrefs=True, useBasicKnowledge=True, useRandomCoords=True,)

    diz = []
    pre_adj = mol.GetAdjacencyMatrix()
    current_dir = os.getcwd()

    for id in ids:
        if conf_search_FF == "MMFF94s":
            prop = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant="MMFF94s")
            ff = AllChem.MMFFGetMoleculeForceField(mol, prop, confId=id)
            ff.Minimize()
            en = float(ff.CalcEnergy())
            econf = (en, id)
            diz.append(econf)
        elif conf_search_FF == "GFNFF":
            scratch_dir_mol_id = os.path.join(scratch_dir, f'{job_id}_{task_id}_{mol_id}_{id}')
            os.makedirs(scratch_dir_mol_id)
            os.chdir(scratch_dir_mol_id)

            input_file_mol_id = f'{mol_id}_{id}.sdf'
            write_mol_to_sdf(mol, input_file_mol_id, id)

            xtb_command = os.path.join(XTB_path, 'xtb')
            output_file_mol_id = f'{mol_id}_{id}.log'
            with open(output_file_mol_id, 'w') as out:
                subprocess.call([xtb_command, '--gfnff', input_file_mol_id, '--opt'],
                                stdout=out, stderr=out)

            log = XtbLog(output_file_mol_id)
            en = float(log.E)
            opt_mol = load_sdf("xtbopt.sdf")[0]
            post_adj = opt_mol.GetAdjacencyMatrix()
            if (pre_adj == post_adj).all():
                opt_conf = opt_mol.GetConformer()
                conf = mol.GetConformer(id)
                for i in range(mol.GetNumAtoms()):
                    pt = opt_conf.GetAtomPosition(i)
                    conf.SetAtomPosition(i, (pt.x, pt.y, pt.z))
                econf = (en, id)
                diz.append(econf)
            os.chdir(current_dir)
            shutil.rmtree(scratch_dir_mol_id)
    
    if E_cutoff_fraction:
        n, diz2 = energy_filter(mol, diz, E_cutoff_fraction)
    else:
        n = mol
        diz2 = diz

    if rmspost and n.GetNumConformers() > 1:
        o, diz3 = postrmsd(n, diz2, rmspost)
    else:
        o = n
        diz3 = diz2
    
    mol = o
    ids = diz3

    ids_to_save = [id for (en, id) in ids[:n_lowest_E_confs_to_save]]
    ens_to_save = [en for (en, id) in ids[:n_lowest_E_confs_to_save]]
    write_mol_to_sdf(mol, os.path.join(save_dir, '{}_confs.sdf'.format(mol_id)), ids_to_save, ens_to_save)
    os.remove(os.path.join(input_dir, f"{mol_id}.in"))

# filter conformers based on relative energy
def energy_filter(m, diz, E_cutoff_fraction):
    diz.sort()
    mini = float(diz[0][0])
    sup = mini + abs(mini) * E_cutoff_fraction
    n = Chem.Mol(m)
    n.RemoveAllConformers()
    n.AddConformer(m.GetConformer(int(diz[0][1])))
    nid = []
    ener = []
    nid.append(int(diz[0][1]))
    ener.append(float(diz[0][0])-mini)
    del diz[0]
    for x,y in diz:
        if x <= sup:
            n.AddConformer(m.GetConformer(int(y)))
            nid.append(int(y))
            ener.append(float(x-mini))
        else:
            break
    diz2 = list(zip(ener, nid))
    return n, diz2


# filter conformers based on geometric RMS
def postrmsd(n, diz2, rmspost):
    diz2.sort(key=lambda x: x[0])
    o = Chem.Mol(n)
    confidlist = [diz2[0][1]]
    enval = [diz2[0][0]]
    nh = Chem.RemoveHs(n)
    del diz2[0]
    for z,w in diz2:
        confid = int(w)
        p=0
        for conf2id in confidlist:
            rmsd = AllChem.GetBestRMS(nh, nh, prbId=confid, refId=conf2id)
            if rmsd < rmspost:
                p=p+1
                break
        if p == 0:
            confidlist.append(int(confid))
            enval.append(float(z))
    diz3 = list(zip(enval, confidlist))
    return o, diz3
