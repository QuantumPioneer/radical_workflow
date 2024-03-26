import logging

logging.basicConfig(level=logging.INFO)

from argparse import ArgumentParser
from pathlib import Path

import pandas as pd
from autoqm.calculation.dft_calculation import dft_scf_qm_descriptor
from autoqm.calculation.utils import (add_qm_des_arguments,
                                                add_shared_arguments)
from rdkit import Chem

logging.basicConfig(level=logging.INFO)

def main(args):
    input_df = pd.read_csv(args.job_input_file)

    job_ids = input_df[args.id].values
    job_xyzs = input_df[args.xyz_column].str.split("\n\n").str[1].values
    job_smis = input_df[args.smiles_column].values

    id_to_xyz_dict = dict(zip(job_ids, job_xyzs))
    id_to_smi_dict = dict(zip(job_ids, job_smis))
    id_to_charge_dict = dict()
    id_to_mult_dict = dict()

    for k, v in id_to_smi_dict.items():
        try:
            mol = Chem.MolFromSmiles(v)
        except Exception as e:
            logging.error(f'Cannot translate job_smi {v} to molecule for species {k}: {e}')

        try:
            charge = Chem.GetFormalCharge(mol)
            id_to_charge_dict[k] = charge
        except Exception as e:
            logging.error(f'Cannot determine molecular charge for species {k} with job_smi {v}: {e}')

        num_radical_elec = 0
        for atom in mol.GetAtoms():
            num_radical_elec += atom.GetNumRadicalElectrons()
        id_to_mult_dict[k] =  num_radical_elec + 1

    submit_dir = Path.cwd().absolute()
    output_dir = submit_dir / "output"
    qm_des_dir = output_dir / "QM_des_calc"

    logging.info("Making inputs and outputs dir...")
    inputs_dir = qm_des_dir / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    outputs_dir = qm_des_dir / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    logging.info("Making helper input files...")
    logging.info(f"Task id: {args.task_id}/{args.num_tasks}")

    id_smi_list = list(zip(job_ids, job_smis))

    for job_id, job_smi in id_smi_list[args.task_id::args.num_tasks]:
        if job_id not in id_to_xyz_dict:
            logging.info(f"Mol id: {job_id} not in xyz dict")
            continue

        logging.info(f"Mol id: {job_id} in xyz dict")

        job_id_div_1000 = job_id // 1000
        subinputs_dir = inputs_dir // f"inputs_{job_id_div_1000}"
        suboutputs_dir = outputs_dir // f"outputs_{job_id_div_1000}"
        suboutputs_dir.mkdir(exist_ok=True)

        job_input_path = subinputs_dir / f"{job_id}.in"
        job_log_path = outputs_dir / f"{job_id}.log"
        job_tmp_input_path = subinputs_dir / f"{job_id}.tmp"
        job_tmp_output_dir = suboutputs_dir / f"{job_id}"

        if job_log_path.exists():
            continue

        if job_input_path.exists():
            continue

        if job_tmp_input_path.exists():
            continue

        subinputs_dir.mkdir(exist_ok=True)

        logging.info(f"Creating input file for {job_id}...")
        with open(job_input_path, "w") as f:
            f.write("")

    logging.info("Starting QM descriptor calculations...")
    for subinputs_folder in inputs_dir.iterdir():
        job_id_div_1000 = int(subinputs_folder.split("_")[1])
        subinputs_dir = inputs_dir // subinputs_folder
        suboutputs_dir = output_dir // f"outputs_{job_id_div_1000}"
        for job_input_file in subinputs_dir.iterdir():
            if job_input_file.endswith(".in"):
                job_input_path = subinputs_dir // job_input_file
                job_id = int(job_input_file.split(".in")[0])
                job_tmp_input_path = subinputs_dir / f"{job_id}.tmp"

                if job_tmp_input_path.exists():
                    continue

                logging.info(f"Starting calculation for {job_id}...")
                job_input_path.rename(job_tmp_input_path)
                charge = id_to_charge_dict[job_id]
                mult = id_to_mult_dict[job_id]
                coords = id_to_xyz_dict[job_id]
                dft_scf_qm_descriptor(
                    job_id=job_id,
                    job_xyz=coords,
                    g16_path=args.g16_path,
                    title_card=args.title_card,
                    n_procs=args.n_procs,
                    job_ram=args.job_ram,
                    charge=charge,
                    mult=mult,
                    scratch_dir=args.scratch_dir,
                    subinputs_dir=subinputs_dir,
                    suboutputs_dir=suboutputs_dir,
                )

if __name__ == "__main__":
    parser = ArgumentParser()
    parser = add_shared_arguments(parser)
    parser = add_qm_des_arguments(parser)
    args = parser.parse_args()
    main(args)
    logging.info("DONE!")