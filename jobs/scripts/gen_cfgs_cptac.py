import os
import yaml
from tqdm import tqdm 
import argparse

# Parse command line arguments
parser = argparse.ArgumentParser(description='Generate configuration files and job scripts.')
parser.add_argument('-m','--magnification', type=int, required=True, help='Magnification level for the preprocessing.')
args = parser.parse_args()

# Update directories based on magnification
base_output_dir = f"/data/cat/ws/s1787956-cobra/data/features-cptac/features-{args.magnification}x"
base_cache_dir = f"/data/cat/ws/s1787956-cobra/data/Cache-CPTAC/Cache-{args.magnification}x"
config_dir = f"/data/horse/ws/s1787956-cobra-horse/code/stamp/src/stamp/configs-cptac-{args.magnification}x"
job_dir = f"/data/horse/ws/s1787956-cobra-horse/code/stamp/jobs/cptac-{args.magnification}x"

base_wsi_dir = "/data/cat/ws/s1787956-cobra/data/CPTAC-WSI"

# Create directories if they don't exist
if not os.path.exists(base_output_dir):
    os.makedirs(base_output_dir)
if not os.path.exists(base_cache_dir):
    os.makedirs(base_cache_dir) 
if not os.path.exists(config_dir):
    os.makedirs(config_dir)
if not os.path.exists(job_dir):
    os.makedirs(job_dir)

mag_dict = {"1":2240.0,"2":1120.,"5": 448.0, "10": 224.0, "20": 112.0, "30":74.666666666667}

# Define the base configuration
base_config = {
    'preprocessing': {
        'output_dir': "",
        'wsi_dir': "",
        'extractor': "",
        'accelerator': "cuda",
        'cache_dir': "",
        'tile_size_um': mag_dict[str(args.magnification)],
        'tile_size_px': 224,
        'max_workers': 14
    }
}

# Define the different feature extractors and cohorts
feature_extractors = ["ctranspath","dinoSSL","virchow2","mahmood-uni", 
                      "mahmood-conch","h_optimus_0","gigapath"] # google model is tf so would avoid.. 
cohorts = [
    "BRCA", "COAD", "LUAD", "LUSC", "LSCC", "HNSCC", "OV", "UCEC", "GBM", "CCRCC", "PDA"
]

# Define the directories
# base_output_dir = "/p/scratch/mfmpm/data/TCGA-feats/features-20x"
# base_wsi_dir = "/p/scratch/mfmpm/data/TCGA"
# base_cache_dir = "/p/scratch/mfmpm/data/TCGA-Cache/Cache-20x"
# config_dir = "/p/scratch/mfmpm/code/stamp/src/stamp/configs-20x"
# job_dir = "/p/scratch/mfmpm/code/stamp/jobs/tcga-20x"

# Create directories if they don't exist
os.makedirs(config_dir, exist_ok=True)
os.makedirs(job_dir, exist_ok=True)

# Generate config files and job scripts
for extractor in tqdm(feature_extractors):
    for cohort in tqdm(cohorts,leave=False):
        config = base_config.copy()
        config['preprocessing']['output_dir'] = f"{base_output_dir}/{extractor}/CPTAC-{cohort}"
        config['preprocessing']['wsi_dir'] = f"{base_wsi_dir}/CPTAC-{cohort}/data"
        config['preprocessing']['extractor'] = extractor
        config['preprocessing']['cache_dir'] = f"{base_cache_dir}/CPTAC-{cohort}"

        config_filename = f"{config_dir}/config_{extractor}_cptac_{cohort}.yaml"
        job_filename = f"{job_dir}/job_{extractor}_cptac_{cohort}.sh"

        # Save the config file
        with open(config_filename, 'w') as config_file:
            yaml.dump(config, config_file)

        # Create the job script
        #         job_script = f"""#!/bin/bash
        # #SBATCH --job-name=preprocess-{extractor}-{cohort}
        # #SBATCH --output="outs/stamp_preprocess_{extractor}_{cohort}_{args.magnification}x_%j.out"
        # #SBATCH --error="errs/stamp_preprocess_{extractor}_{cohort}_{args.magnification}x_%j.err"
        # #SBATCH --ntasks=1
        # #SBATCH --nodes=1
        # #SBATCH --gres=gpu:4
        # #SBATCH --cpus-per-task=48
        # #SBATCH --mem=500G
        # #SBATCH --time=10:00:00
        # #SBATCH --account=mfmpm
        # #SBATCH --partition=booster

        # cd /p/scratch/mfmpm/code/stamp
        # module load CUDA
        # source /p/scratch/mfmpm/code/stamp/.venv/bin/activate
        # export XDG_CACHE_HOME="/p/scratch/mfmpm/tim-cache"

        # CUDA_VISIBLE_DEVICES=0 stamp -c {config_filename} preprocess &
        # CUDA_VISIBLE_DEVICES=1 stamp -c {config_filename} preprocess &
        # CUDA_VISIBLE_DEVICES=2 stamp -c {config_filename} preprocess &
        # CUDA_VISIBLE_DEVICES=3 stamp -c {config_filename} preprocess 

        # wait
        #         """
        job_script = f"""#!/bin/bash
#SBATCH --job-name={cohort}-{extractor}-cptac-preprocess
#SBATCH --output="outs/cptac-stamp_preprocess_{extractor}_{cohort}_{args.magnification}x_%j.out"
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=14
#SBATCH --mem=100G
#SBATCH --time=14:00:00
#SBATCH --account=p_scads_pathology
#SBATCH --partition=capella

cd /data/horse/ws/s1787956-cobra-horse/code/stamp
module load CUDA
export XDG_CACHE_HOME="/data/horse/ws/s1787956-Cache"

stamp -c {config_filename} preprocess
        """

        # Save the job script
        with open(job_filename, 'w') as job_file:
            job_file.write(job_script)