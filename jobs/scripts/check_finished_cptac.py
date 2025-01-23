import os
import argparse
import subprocess
from tqdm import tqdm
import glob
from concurrent.futures import ThreadPoolExecutor


def count_files(directory, extension):
    return len([f for f in os.listdir(directory) if f.endswith(extension)])


def count_non_empty_h5_files(directory, num_workers=8):
    h5s = glob.glob(os.path.join(directory, "*.h5"))

    def is_broken(file):
        return os.path.getsize(file) <= 800

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        broken = list(tqdm(executor.map(is_broken, h5s), total=len(h5s),leave=False))
        broken = [h5s[i] for i, is_broken in enumerate(broken) if is_broken]
    return (len(h5s) - len(broken)), broken


def check_preprocessing(
    cohorts,
    feature_extractors,
    wsi_base_dir,
    h5_base_dir,
    summary_only=False,
    delh5s=False,
    broken_file_log_path=None,
):
    summary = {
        cohort: {model: None for model in feature_extractors} for cohort in cohorts
    }
    total_h5_files = 0
    for model in tqdm(feature_extractors):
        if not summary_only:
            tqdm.write(f"\033[1m{model}\033[0m")
        for cohort in tqdm(cohorts, leave=False):
            wsi_dir = os.path.join(
                wsi_base_dir, f"CPTAC-{cohort}", f"data"
            )
            num_wsi_files = count_files(wsi_dir, ".svs")

            model_dir = os.path.join(h5_base_dir, model, f"CPTAC-{cohort}")
            if os.path.exists(model_dir):
                subdirs = [
                    d
                    for d in os.listdir(model_dir)
                    if os.path.isdir(os.path.join(model_dir, d)) and model in d
                ]
                if subdirs:
                    h5_dir = os.path.join(model_dir, subdirs[0])
                else:
                    continue
                if os.path.exists(h5_dir):
                    num_h5_files, broken = count_non_empty_h5_files(h5_dir)
                    total_h5_files += num_h5_files
                    if delh5s and len(broken) > 0:
                        for file in broken:
                            tqdm.write(f"Deleting broken H5 file: {file}")
                            with open(broken_file_log_path, "a") as log_file:
                                log_file.write(f"{file}\n")
                            os.remove(file)
                    elif len(broken) > 0:
                        for b in broken:
                            tqdm.write(
                                f"Broken H5 files found for cohort {cohort}, model {model}: {b}"
                            )
                            with open(broken_file_log_path, "a") as log_file:
                                log_file.write(f"{b}\n")
                else:
                    continue
                if num_h5_files == num_wsi_files:
                    if not summary_only:
                        tqdm.write(
                            f"\033[92mCohort \033[1m{cohort}\033[0m\033[92m is completely processed for model \033[1m{model}\033[0m\033[92m with {num_wsi_files} WSIs\033[0m"
                        )
                elif num_h5_files > 0:
                    if not summary_only:
                        tqdm.write(
                            f"Cohort \033[1m{cohort}\033[0m is partially processed for model \033[1m{model}\033[0m: {num_h5_files}/{num_wsi_files} slides processed"
                        )
                summary[cohort][model] = (num_wsi_files, num_h5_files)
            else:
                summary[cohort][model] = (num_wsi_files, 0)
        if not summary_only:
            tqdm.write("")
    print(f"\033[1mTotal number of proper H5 files: {total_h5_files}\033[0m")

    print("\033[1mSummary of missing slides:\033[0m")
    sorted_cohorts = sorted(
        cohorts,
        key=lambda cohort: max(
            summary[cohort][model][0] for model in feature_extractors
        ),
        reverse=True,
    )
    for cohort in sorted_cohorts:
        max_model = max(summary[cohort], key=lambda model: summary[cohort][model][1])
        max_h5_files = summary[cohort][max_model][1]
        if all(
            summary[cohort][model][0] == summary[cohort][model][1]
            for model in feature_extractors
        ):
            print(
                f"\033[92mAll models completed processing {max_h5_files}/{summary[cohort][max_model][0]} slides for cohort \033[1m{cohort}\033[0m\033[92m\033[0m"
            )
        elif all(
            summary[cohort][model][1] == max_h5_files for model in feature_extractors
        ):
            print(
                f"All models processed {max_h5_files}/{summary[cohort][max_model][0]} slides for cohort \033[1m{cohort}\033[0m"
            )
        else:
            print(
                f"Cohort \033[1m{cohort}\033[0m: Model \033[1m{max_model}\033[0m has the maximum number of H5 files: {max_h5_files}"
            )
            for model in feature_extractors:
                num_wsi_files, num_h5_files = summary[cohort][model]
                missing = num_wsi_files - num_h5_files
                print(
                    f"Cohort \033[1m{cohort}\033[0m: Model \033[1m{model}\033[0m is missing {missing} slides ({num_h5_files}/{num_wsi_files} processed)"
                )
        print("")


def delete_cache_and_resubmit_jobs(
    cohorts,
    feature_extractors,
    wsi_base_dir,
    h5_base_dir,
    magnification,
    delete_cache=False,
):
    cache_base_dir = f"data/cat/ws/s1787956-cobra/data/Cache-CPTAC/Cache-{magnification}x"
    for cohort in cohorts:
        print(cohort)
        wsi_dir = os.path.join(wsi_base_dir, f"CPTAC-{cohort}", f"data")
        for model in feature_extractors:
            model_dir = os.path.join(h5_base_dir, model, f"CPTAC-{cohort}")
            if os.path.exists(model_dir):
                subdirs = [
                    d
                    for d in os.listdir(model_dir)
                    if os.path.isdir(os.path.join(model_dir, d)) and model in d
                ]
                if subdirs:
                    h5_dir = os.path.join(model_dir, subdirs[0])
                else:
                    continue
                if os.path.exists(h5_dir):
                    missing_files = get_missing_wsi_files(wsi_dir, h5_dir)
                    for file in missing_files:
                        # cache_file = os.path.join(cache_base_dir, os.path.basename(file).split('.')[0] + '.zip')
                        cache_files = [
                            f
                            for f in os.listdir(
                                os.path.join(cache_base_dir, f"CPTAC-{cohort}")
                            )
                            if f.startswith(os.path.basename(file).split(".")[0])
                        ]
                        if len(cache_files) == 0:
                            print(
                                f"No cache files found for {file} in {os.path.join(cache_base_dir,f'CPTAC-{cohort}')}"
                            )
                            continue
                        if delete_cache:
                            for cache_file in cache_files:
                                cache_file_path = os.path.join(
                                    cache_base_dir, f"CPTAC-{cohort}", cache_file
                                )
                                print(f"Deleting cache file: {cache_file_path}")
                                os.remove(cache_file_path)
                        # if os.path.exists(cache_file):
                        #    os.remove(cache_file)
                    if missing_files:
                        print(
                            f"Submitting jobs for model {model}, cohort {cohort}, magnification {magnification}x"
                        )
                        subprocess.run(
                            [
                                "bash",
                                "submit_jobs_cptac.sh",
                                model,
                                cohort,
                                "1",
                                "1",
                                f"{magnification}x",
                            ]
                        )
        print("")
    # if __name__ == "__main__":
    #     feature_extractors = ["virchow2", "mahmood-uni", "mahmood-conch", "h_optimus_0", "gigapath","dinoSSL","ctranspath"]
    #     cohorts = [
    #     "GBM", "LGG", "BLCA", "LUAD", "BRCA", "DLBC", "CHOL", "ESCA", "CRC", "CESC",
    #     "UCS", "UCEC", "THYM", "THCA", "TGCT", "STAD", "SKCM", "SARC", "PRAD", "PCPG",
    #     "PAAD", "OV", "MESO", "LUSC", "LIHC", "KIRP", "KIRC", "KICH", "HNSC"
    #     ]
    #     parser = argparse.ArgumentParser(description="Check preprocessing status of WSIs")
    #     parser.add_argument('--print-missing', action='store_true', help="Print missing WSIs")
    #     parser.add_argument('--cohorts', nargs='+', default=cohorts, help="List of cohorts to check, e.g., --cohorts GBM LGG BLCA")
    #     parser.add_argument('--models', nargs='+', default=feature_extractors, help="List of models to check, e.g., --models virchow2 mahmood-uni")
    #     parser.add_argument('-m',"--magnification", type=int, default=5, help="Magnification level of the WSIs")
    #     parser.add_argument('--resubmit', action='store_true', help="Delete cache and resubmit jobs for missing WSIs")
    #     args = parser.parse_args()
    #     wsi_base_dir = "/p/scratch/mfmpm/data/TCGA"
    #     h5_base_dir = f"/p/scratch/mfmpm/data/TCGA-feats/features-{args.magnification}x"
    #     if args.print_missing:
    #         print_missing_wsi_files(args.cohorts, args.models, wsi_base_dir, h5_base_dir)
    #     if args.resubmit:
    #         delete_cache_and_resubmit_jobs(args.cohorts, args.models, wsi_base_dir, h5_base_dir, args.magnification)
    #     check_preprocessing(args.cohorts, args.models, wsi_base_dir, h5_base_dir)


def get_missing_wsi_files(wsi_dir, h5_dir):
    wsi_files = {f for f in os.listdir(wsi_dir) if f.endswith(".svs")}
    h5_files = {
        f.replace(".h5", ".svs")
        for f in os.listdir(h5_dir)
        if f.endswith(".h5") and os.path.getsize(os.path.join(h5_dir, f)) > 0
    }
    missing_files = wsi_files - h5_files
    return [os.path.join(wsi_dir, f) for f in missing_files]


def print_missing_wsi_files(
    print_cohorts, feature_extractors, wsi_base_dir, h5_base_dir
):
    for cohort in print_cohorts:
        print(cohort)
        wsi_dir = os.path.join(wsi_base_dir, f"CPTAC-{cohort}", f"data")
        for model in feature_extractors:
            print(model)
            model_dir = os.path.join(h5_base_dir, model, f"CPTAC-{cohort}")
            if os.path.exists(model_dir):
                subdirs = [
                    d
                    for d in os.listdir(model_dir)
                    if os.path.isdir(os.path.join(model_dir, d)) and model in d
                ]
                if subdirs:
                    h5_dir = os.path.join(model_dir, subdirs[0])
                else:
                    continue
                if os.path.exists(h5_dir):
                    missing_files = get_missing_wsi_files(wsi_dir, h5_dir)
                    for file in missing_files:
                        print(file)
        print("")


if __name__ == "__main__":
    feature_extractors = [
        "virchow2",
        "gigapath",
        "h_optimus_0",
        "mahmood-uni",
        "mahmood-conch",
        "dinoSSL",
        "ctranspath",
    ]
    cohorts = [
        "BRCA",
        "LUAD",
        "LUSC",
        "COAD",
    ]
    parser = argparse.ArgumentParser(description="Check preprocessing status of WSIs")
    parser.add_argument(
        "-p", "--print-missing", action="store_true", help="Print missing WSIs"
    )
    parser.add_argument(
        "-c",
        "--cohorts",
        nargs="+",
        default=cohorts,
        help="List of cohorts to check, e.g., --cohorts GBM LGG BLCA",
    )
    parser.add_argument(
        "-f",
        "--models",
        nargs="+",
        default=feature_extractors,
        help="List of models to check, e.g., --models virchow2 mahmood-uni",
    )
    parser.add_argument(
        "-m",
        "--magnification",
        type=int,
        default=5,
        help="Magnification level of the WSIs",
    )
    parser.add_argument(
        "-r", "--resubmit", action="store_true", help="Resubmit jobs for missing WSIs"
    )
    parser.add_argument(
        "-s", "--summary_only", action="store_true", help="Print summary only"
    )
    parser.add_argument(
        "-d", "--delete_cache", action="store_true", help="Delete cache files"
    )
    parser.add_argument(
        "-x", "--check_h5s", action="store_true", help="Check H5 files only"
    )
    parser.add_argument("-e", "--del_h5s", action="store_true", help="Delete H5 files")
    parser.add_argument(
        "-b",
        "--broken_file_log_path",
        type=str,
        default="/data/horse/ws/s1787956-cobra-horse/code/stamp/jobs/scripts/broken-cptac.txt",
        help="Path to log broken H5 files",
    )
    args = parser.parse_args()
    wsi_base_dir = "/data/cat/ws/s1787956-cobra/data/CPTAC-WSI"
    h5_base_dir = (
        f"/data/cat/ws/s1787956-cobra/data/features-cptac/features-{args.magnification}x"
    )
    print(f"Checking CPTAC preprocessing status for magnification {args.magnification}x")
    if args.print_missing:
        print_missing_wsi_files(args.cohorts, args.models, wsi_base_dir, h5_base_dir)
    if args.check_h5s:
        check_preprocessing(
            args.cohorts,
            args.models,
            wsi_base_dir,
            h5_base_dir,
            args.summary_only,
            delh5s=args.del_h5s,
            broken_file_log_path=args.broken_file_log_path,
        )
    if args.resubmit:
        delete_cache_and_resubmit_jobs(
            args.cohorts,
            args.models,
            wsi_base_dir,
            h5_base_dir,
            args.magnification,
            args.delete_cache,
        )
    # else:
    #     #check_preprocessing(args.cohorts,args.models,wsi_base_dir,h5_base_dir,args.summary_only)
    #     print("Please specify an action to perform with the -p, -r, or -x flags")
