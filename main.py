from argparse import ArgumentParser, Namespace
import os
import shutil
import time
import yaml

import pandas as pd

import rdkit.Chem as Chem

from lib import create_logger
from lib import csearch
from lib import xtb_optimization
from lib import dft_scf

XTB_PATH = '/home/gridsan/oscarwu/bin/anaconda3/envs/QM_descriptors/bin/'
G16_PATH = '/home/gridsan/oscarwu/GRPAPI/Software/g16/'

parser = ArgumentParser()
parser.add_argument('--ismiles', type=str, required=False,
                    help='input smiles included in a .csv file')
# parser.add_argument('--output', type=str, default='QM_descriptors.pickle',
#                     help='output as a .pickle file')
# conformer searching
parser.add_argument('--MMFF_conf_folder', type=str, default='MMFF_conf',
                    help='folder for MMFF searched conformers')
parser.add_argument('--nconf', type=int, default=500,
                    help='number of MMFF conformers')
parser.add_argument('-max_conf_try', type=int, default=2000,
                    help='maximum attempt for conformer generating, '
                         'this is useful for molecules with many chiral centers.')
parser.add_argument('-rmspre', type=float, required=False,
                        help='rms threshold pre optimization')
parser.add_argument('--rmspost', type=float, required=False, default=0.4,
                    help='rms threshold post MMFF minimization')
parser.add_argument('--E_cutoff', type=float, required=False, default=10.0,
                    help='energy window for MMFF minimization')
parser.add_argument('--MMFF_threads', type=int, required=False, default=40,
                    help='number of process for the MMFF conformer searching')
parser.add_argument('--timeout', required=False, default=600,
                    help='time window for each MMFF conformer searching sub process')
# xtb optimization
parser.add_argument('--xtb_folder', type=str, default='XTB_opt',
                    help='folder for XTB optimization')

# DFT calculation
parser.add_argument('--DFT_folder', type=str, default='DFT',
                    help='folder for DFT calculation')
parser.add_argument('--DFT_theory', type=str, default='b3lyp/def2svp',
                    help='level of theory for the DFT calculation')
parser.add_argument('--DFT_n_procs', type=int, default=4,
                    help='number of process for DFT calculations')
parser.add_argument('--DFT_job_ram', type=int, default=3000,
                    help='amount of ram (MB) allocated for each DFT calculation')

args = parser.parse_args()

name = os.path.splitext(args.ismiles)[0]
logger = create_logger(name=name)

df = pd.read_csv(args.ismiles, index_col=0)
# create id to smile mapping
molid_to_smi_dict = dict(zip(df.id, df.smiles))

# conformer searching

logger.info('starting MMFF conformer searching')
supp = (x for x in df[['id', 'smiles']].values)
conf_sdfs = csearch(supp, len(df), args, logger)

# xtb optimization

logger.info('starting GFN2-XTB structure optimization for the lowest MMFF conformer')
os.makedirs(args.xtb_folder,exist_ok=True)

opt_sdfs = []
for conf_sdf in conf_sdfs:
    try:
        shutil.copyfile(os.path.join(args.MMFF_conf_folder, conf_sdf),
                        os.path.join(args.xtb_folder, conf_sdf))
        opt_sdf = xtb_optimization(args.xtb_folder, conf_sdf, XTB_PATH, logger)
        opt_sdfs.append(opt_sdf)
    except Exception as e:
        logger.error('XTB optimization for {} failed: {}'.format(os.path.splitext(conf_sdf)[0], e))

# G16 DFT calculation
os.makedirs(args.DFT_folder, exist_ok=True)

qm_descriptors = dict()
for opt_sdf in opt_sdfs:
    try:
        molid = opt_sdf.split('_')[0]
        smi = molid_to_smi_dict[molid]
        mol = Chem.MolFromSmiles(smi)
        charge = Chem.GetFormalCharge(mol)
    except Exception as e:
        logger.error(f'Cannot determine molecular charge for species {molid}')

    try:
        shutil.copyfile(os.path.join(args.xtb_folder, opt_sdf),
                        os.path.join(args.DFT_folder, opt_sdf))
        time.sleep(1)
    except Exception as e:
        logger.error(f'file IO error.')

    try:
        qm_descriptor = dft_scf(args.DFT_folder, opt_sdf, G16_PATH, args.DFT_theory, args.DFT_n_procs,
                                logger, args.DFT_job_ram, charge)
        qm_descriptors[molid] = (smi, qm_descriptor)
    except Exception as e:
        logger.error('Gaussian optimization for {} failed: {}'.format(os.path.splitext(opt_sdf)[0], e))

with open('qm_descriptors.yaml', 'w') as output:
    yaml.dump(qm_descriptors, output)
# qm_descriptors = pd.DataFrame(qm_descriptors)
# qm_descriptors.to_pickle(args.output)

