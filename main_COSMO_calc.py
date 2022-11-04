from argparse import ArgumentParser
import os
import shutil
import time
import tarfile
import csv

import pickle as pkl
import pandas as pd
import traceback

from rdkit import Chem

from lib.wft_calculation import generate_dlpno_sp_input
from lib.cosmo_calculation import cosmo_calc

parser = ArgumentParser()
parser.add_argument('--input_smiles', type=str, required=True,
                    help='input smiles included in a .csv file')
parser.add_argument('--output_folder', type=str, default='output',
                    help='output folder name')
parser.add_argument('--scratch_dir', type=str, required=True,
                    help='scfratch directory')
parser.add_argument('--xyz_DFT_opt', type=str, default=None,
                    help='pickle file containing a dictionary to map between the mol_id and DFT-optimized xyz for following calculations',)

# Turbomole and COSMO calculation
parser.add_argument('--COSMO_folder', type=str, default='COSMO_calc',
                    help='folder for COSMO calculation',)
parser.add_argument('--COSMO_temperatures', type=str, nargs="+", required=False, default=['297.15', '298.15', '299.15'],
                    help='temperatures used for COSMO calculation')
parser.add_argument('--COSMO_input_pure_solvents', type=str, required=False, default='common_solvent_list_final.csv',
                    help='input file containing pure solvents used for COSMO calculation.')
parser.add_argument('--COSMOtherm_path', type=str, required=False, default=None,
                    help='path to COSMOthermo')
parser.add_argument('--COSMO_database_path', type=str, required=False, default=None,
                    help='path to COSMO_database')

args = parser.parse_args()

# input files
with open(args.xyz_DFT_opt, "rb") as f:
    xyz_DFT_opt = pkl.load(f)

df = pd.read_csv(args.input_smiles, index_col=0)

# create id to smile mapping
mol_id_to_smi_dict = dict(zip(df.id, df.smiles))
mol_id_to_charge_dict = dict()
mol_id_to_mult_dict = dict()
for k, v in mol_id_to_smi_dict.items():
    try:
        mol = Chem.MolFromSmiles(v)
    except Exception as e:
        print(f'Cannot translate smi {v} to molecule for species {k}')

    try:
        charge = Chem.GetFormalCharge(mol)
        mol_id_to_charge_dict[k] = charge
    except Exception as e:
        print(f'Cannot determine molecular charge for species {k} with smi {v}')

    num_radical_elec = 0
    for atom in mol.GetAtoms():
        num_radical_elec += atom.GetNumRadicalElectrons()
    mol_id_to_mult_dict[k] =  num_radical_elec + 1

submit_dir = os.path.abspath(os.getcwd())
project_dir = os.path.abspath(os.path.join(args.output_folder))
COSMO_dir = os.path.join(project_dir, args.COSMO_folder)

df_pure = pd.read_csv(os.path.join(submit_dir,args.COSMO_input_pure_solvents))
df_pure = df_pure.reset_index()
COSMOTHERM_PATH = args.COSMOtherm_path
COSMO_DATABASE_PATH = args.COSMO_database_path

for subinputs_folder in os.listdir(os.path.join(COSMO_dir, "inputs")):
    ids = subinputs_folder.split("_")[1]
    subinputs_dir = os.path.join(COSMO_dir, "inputs", subinputs_folder)
    suboutputs_dir = os.path.join(COSMO_dir, "outputs", f"outputs_{ids}")
    for input_file in os.listdir(subinputs_dir):
        if ".in" in input_file:
            mol_id = input_file.split(".in")[0]
            try:
                os.rename(os.path.join(subinputs_dir, input_file), os.path.join(subinputs_dir, f"{mol_id}.tmp"))
            except:
                continue
            else:
                ids = str(int(int(mol_id.split("id")[1])/1000))
                charge = mol_id_to_charge_dict[mol_id]
                mult = mol_id_to_mult_dict[mol_id]
                coords = xyz_DFT_opt[mol_id]
                tmp_mol_dir = os.path.join(subinputs_dir, mol_id)
                os.makedirs(tmp_mol_dir, exist_ok=True)
                cosmo_calc(mol_id, COSMOTHERM_PATH, COSMO_DATABASE_PATH, charge, mult, args.COSMO_temperatures, df_pure, coords, args.scratch_dir, tmp_mol_dir, suboutputs_dir, subinputs_dir)
