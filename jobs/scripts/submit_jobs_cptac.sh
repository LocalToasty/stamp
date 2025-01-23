#!/bin/bash

# Usage: ./submit_jobs.sh <models> <cohorts> <jobs_per_round> <rounds>
# Example: ./submit_jobs.sh "virchow2 mahmood-uni" "GBM LGG" 3 2

# Default values  "DLBC" "MESO" 
default_models=("ctranspath" "dinoSSL" "virchow2" "mahmood-conch" "h_optimus_0" "gigapath" "mahmood-uni")
default_cohorts=("BRCA" "LUAD" "COAD" "LUSC" "LSCC" "HNSCC" "OV" "UCEC" "GBM" "CCRCC" "PDA")
# big models: "h_optimus_0 gigapath virchow2"

# done for 10x: 
# cohorts: DLBC, MESO 
# models: 

# bash submit_jobs.sh "virchow2 ctranspath dinoSSL mahmood-conch h_optimus_0 gigapath  mahmood-uni" "BRCA GBM LGG BLCA LUAD LUSC SARC THCA CRC UCEC KIRC HNSC" 1 3 20x

# big cohorts: "GBM LGG BRCA LUAD CRC LUSC KIRC UCEC THCA SARC"

# Cohorts list:
# "BRCA GBM LGG BLCA LUAD CHOL ESCA CRC CESC UCS UCEC THYM THCA TGCT STAD SKCM SARC PRAD PCPG PAAD OV LUSC LIHC KIRP KIRC KICH HNSC DLBC MESO"

# Assign command line arguments or default values
models=(${1:-${default_models[@]}})
cohorts=(${2:-${default_cohorts[@]}})
jobs_per_round=${3:-1}
rounds=${4:-2}
magnification=${5:-20x}

for model in ${models[@]}; do
    echo "$model"
    for cohort in ${cohorts[@]}; do
        previous_jobs=""
        for round in $(seq 1 $rounds); do
            current_jobs=""
            for job_num in $(seq 1 $jobs_per_round); do
                job_file="../cptac-${magnification}/job_${model}_cptac_${cohort}.sh"
                if [ -z "$previous_jobs" ]; then
                    job_id=$(sbatch $job_file | awk '{print $4}')
                else
                    job_id=$(sbatch --dependency=afterany:$previous_jobs $job_file | awk '{print $4}')
                fi
                current_jobs="$current_jobs:$job_id"
            done
            previous_jobs=${current_jobs#:}
        done
    done
done

