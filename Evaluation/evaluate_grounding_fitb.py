import os
import ast
import pathlib
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser

from copy import deepcopy
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
import random
import open_clip

try:
    from tqdm import tqdm
except ImportError:
    # If tqdm is not available, provide a mock version of it
    def tqdm(x):
        return x

import eval_utils

parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
parser.add_argument('--batch_size', type=int, default=50,
                    help='Batch size to use')
parser.add_argument('--num_workers', type=int, default=1,
                    help=('Number of processes to use for data loading. '
                          'Defaults to `min(8, num_cpus)`'))
parser.add_argument('--gpu', type=int, default=None,
                    help='gpu id to use')
parser.add_argument('--dims4fid', type=int, default=2048,
                    help=('Dimensionality of Inception features to use. '
                          'By default, uses pool3 features'))
parser.add_argument('--data_path', type=str, default='/data/path/')
parser.add_argument('--img_folder_path', type=str, default="/data/path/xxx")
parser.add_argument('--pretrained_evaluator_ckpt', type=str, default='./compatibility_evaluator/ifashion-ckpt/fashion_evaluator_0.0001_0.0001_test.pth')
parser.add_argument('--output_dir', type=str, default="/output/path")
parser.add_argument('--dataset', type=str, default="ifashion")
parser.add_argument('--eval_version', type=str, default="difashion-xxx")
parser.add_argument('--ckpts', type=str, default=None)
parser.add_argument('--task', type=str, default="FITB")
parser.add_argument('--num_classes', type=int, default=50)
parser.add_argument('--sim_func', type=str, default="cosine")
parser.add_argument('--lpips_net', type=str, default="vgg")
parser.add_argument('--seed', type=int, default=123)
parser.add_argument('--log_name', type=str, default="log")
parser.add_argument('--mode', type=str, default="valid")
parser.add_argument('--hist_scales', type=float, default=4.0)
parser.add_argument('--mutual_scales', type=float, default=5.0)
parser.add_argument('--cate_scales', type=float, default=12.0)

SPECIAL_CATES = ["shoes", "pants", "sneakers", "boots", "earrings", "slippers", "sandals"]
os.environ["TOKENIZERS_PARALLELISM"] = "false" 

class ImagePathDataset(Dataset):
    def __init__(self, folder_path, paths, trans=None, do_normalize=True):
        self.folder_path = folder_path
        self.paths = paths
        self.trans = trans
        self.do_normalize = do_normalize
    
    def __len__(self):
        return len(self.paths)
    
    def __getitem__(self, idx):
        path = os.path.join(self.folder_path, self.paths[idx])
        img = Image.open(path).convert('RGB')
        # if self.trans is not None:
        #     img = self.trans(img)
        # if self.do_normalize:
        #     img = 2 * img - 1
        return img

class FashionEvalDataset(Dataset):
    def __init__(self, data):
        self.data = data

    def __len__(self):
        return len(self.data)
    
    def __getitem__(self, index):
        return self.data[index]

class FashionRetrievalDataset(Dataset):
    def __init__(self, gen_images, candidates):
        self.gen_images = gen_images
        self.candidates = candidates

    def __len__(self):
        return len(self.gen_images)
    
    def __getitem__(self, index):
        return self.gen_images[index], self.candidates[index]

class FashionPersonalDiffDataset(Dataset):
    def __init__(self, data):
        self.data = data
    
    def __len__(self):
        return len(self.data["gen1"])
    
    def __getitem__(self, index):
        gen1 = self.data["gen1"][index]
        gen2 = self.data["gen2"][index]
        hist1 = self.data["hist1"][index]
        hist2 = self.data["hist2"][index]

        return gen1, gen2, hist1, hist2

class FashionPersonalSimDataset(Dataset):
    def __init__(self, data):
        self.data = data
    
    def __len__(self):
        return len(self.data["gen"])
    
    def __getitem__(self, index):
        gen = self.data["gen"][index]
        hist = self.data["hist"][index]

        return gen, hist

def cate_trans(cid, id_cate_dict):

    def contains_any_special_cate(category, special_cates):
        for special_cate in special_cates:
            if special_cate in category:
                return True
        return False
    
    category = id_cate_dict[cid]
    if contains_any_special_cate(category, SPECIAL_CATES):
        prompt = "A photo of a pair of " + category + ", on white background"
    else:
        prompt = "A photo of a " + category + ", on white background"

    return prompt

def main():
    args = parser.parse_args()
    set_random_seed(args.seed)

    if args.dataset == "ifashion":
        args.data_path = '../datasets/ifashion'
        args.pretrained_evaluator_ckpt = './compatibility_evaluator/ifashion-ckpt/ifashion_evaluator.pth'
        args.output_dir = '../output/ifashion'
    elif args.dataset == "polyvore":
        args.data_path = '../datasets/polyvore'
        args.pretrained_evaluator_ckpt = './compatibility_evaluator/polyvore-ckpt/polyvore_evaluator.pth'
        args.output_dir = '../output/polyvore'
    else:
        raise ValueError(f"Invalid dataset: {args.dataset}.")

    if args.mode == "valid":
        eval_path = os.path.join(args.output_dir, args.eval_version, "eval")
    else:
        eval_path = os.path.join(args.output_dir, args.eval_version, "eval-test")

    if args.ckpts != "all":
        ckpts = ast.literal_eval(args.ckpts)
    else:
        dirs = os.listdir(eval_path)
        dirs = [d.rstrip(".npy") for d in dirs if d.startswith(f"{args.task}-checkpoint") and d.endswith(".npy") and not d.endswith("preds.npy")]
        dirs = sorted(dirs, key=lambda x: int(x.split("-")[2]))
        ckpts = [int(d.split('-')[2]) for d in dirs]
    
    scale = f"cate{args.cate_scales}-mutual{args.mutual_scales}-hist{args.hist_scales}"

    if args.gpu is None:
        device = torch.device('cuda' if (torch.cuda.is_available()) else 'cpu')
    else:
        device = torch.device(f"cuda:{args.gpu}")
    print(f"Evaluate on device {device}")

    num_workers = args.num_workers

    id_cate_dict = np.load(os.path.join(args.data_path, "id_cate_dict.npy"), allow_pickle=True).item()
    all_img_paths = np.load(os.path.join(args.data_path, "all_item_image_paths.npy"), allow_pickle=True)
    cnn_features_clip = np.load(os.path.join(args.data_path, "cnn_features_clip.npy"), allow_pickle=True)
    cnn_features_clip = torch.tensor(cnn_features_clip)

    img_dataset = ImagePathDataset(args.img_folder_path, all_img_paths)

    if args.mode == "valid":
        history = np.load(os.path.join(args.data_path, "processed", "valid_history_clipembs.npy"), allow_pickle=True).item()
        fitb_candidates = np.load(os.path.join(args.data_path, "fitb_valid_retrieval_candidates.npy"), allow_pickle=True).item()
    else:
        history = np.load(os.path.join(args.data_path, "processed", "test_history_clipembs.npy"), allow_pickle=True).item()
        fitb_candidates = np.load(os.path.join(args.data_path, "fitb_test_retrieval_candidates.npy"), allow_pickle=True).item()
        test_grd = np.load(os.path.join(args.data_path, "test_grd.npy"), allow_pickle=True).item()
        fitb_test_dict = np.load(os.path.join(args.data_path, "fitb_test_dict.npy"), allow_pickle=True).item()

    eval_save_path = os.path.join(eval_path, f"eval_results_grounding.npy")
    if not os.path.exists(eval_save_path):
        all_eval_metrics = {}
    else:
        all_eval_metrics = np.load(eval_save_path, allow_pickle=True).item()

    for ckpt in ckpts:
        try:
            gen_data = np.load(os.path.join(eval_path, f"{args.task}-checkpoint-{ckpt}-{scale}-preds.npy"), allow_pickle=True).item()
            pred = True
        except:
            gen_data = np.load(os.path.join(eval_path, f"{args.task}-checkpoint-{ckpt}-{scale}.npy"), allow_pickle=True).item()
            pred = False

        grd_data = np.load(os.path.join(eval_path, f"{args.task}-grd-new.npy"), allow_pickle=True).item()

        if ckpt not in all_eval_metrics:
            all_eval_metrics[ckpt] = {}
        else:
            print(f"checkpoint-{ckpt} has already been evaluated. Skip.")
            continue
        
        if not pred:
            # -------------------------------------------------------------- #
            #               Calculating CLIP Retrieval Acc                   #
            # -------------------------------------------------------------- #
            print("Calculating CLIP Retrieval Accuracy...")
            _, _, img_trans = open_clip.create_model_and_transforms('ViT-H-14', pretrained="laion2b-s32b-b79K")
            gen4clip = []
            all_candidates = []
            for uid in gen_data:
                for oid in gen_data[uid]:
                    for img_path in gen_data[uid][oid]["image_paths"]:
                        im = Image.open(img_path)
                        gen4clip.append(img_trans(im))
                    
                    all_candidates.append(torch.tensor(fitb_candidates[int(uid)][int(oid)]))
            
            assert len(gen4clip) == len(all_candidates)

            gen_retrieval_dataset_clip = FashionRetrievalDataset(gen4clip, all_candidates)
            clip_acc, all_preds = eval_utils.calculate_clip_retrieval_acc_given_data2(
                gen_retrieval_dataset_clip,
                cnn_features_clip,
                batch_size=args.batch_size,
                device=device,
                num_workers=num_workers,
                similarity_func=args.sim_func
            )

            # save retrieval results
            cnt = 0
            for uid in gen_data:
                for oid in gen_data[uid]:
                    gen_num = len(gen_data[uid][oid]["image_paths"])
                    gen_idxs = []
                    for _ in range(gen_num):
                        gen_idxs.append(all_preds[cnt])
                        cnt += 1
                    gen_data[uid][oid]["images"] = gen_idxs
            
            assert cnt == len(all_preds)
            np.save(os.path.join(eval_path, f"{args.task}-checkpoint-{ckpt}-{scale}-preds.npy"), np.array(gen_data))

            torch.cuda.empty_cache()

        _, _, img_trans = open_clip.create_model_and_transforms('ViT-H-14', pretrained="laion2b-s32b-b79K")
        gen4clip = []
        gen4lpips = []

        grd4clip = []
        grd4lpips = []

        txt4eval = []

        total_cnt = 0
        correct = 0
        for uid in gen_data:
            for oid in gen_data[uid]:
                for gen_idx in gen_data[uid][oid]["images"]:
                    gen_idx = gen_idx.item()
                    gen_iid = fitb_candidates[int(uid)][int(oid)][gen_idx]
                    grd_iid = fitb_candidates[int(uid)][int(oid)][0]

                    if gen_idx == 0:
                        correct += 1
                    total_cnt += 1

                    gen_im = img_dataset[gen_iid]
                    gen4clip.append(img_trans(gen_im))
                    gen4lpips.append(eval_utils.im2tensor_lpips(gen_im))

                    grd_im = img_dataset[grd_iid]
                    grd4clip.append(img_trans(grd_im))
                    grd4lpips.append(eval_utils.im2tensor_lpips(grd_im))

                for cate in gen_data[uid][oid]["cates"]:
                    txt4eval.append(cate_trans(cate.item(), id_cate_dict))

        clip_acc = correct / total_cnt
        all_eval_metrics[ckpt]["CLIP accuracy"] = clip_acc
        np.save(eval_save_path, np.array(all_eval_metrics))

        # -------------------------------------------------------------- #
        #          Calculating CLIP score and CLIP image score           #
        # -------------------------------------------------------------- #
        gen_dataset_clip = FashionEvalDataset(gen4clip)
        grd_dataset_clip = FashionEvalDataset(grd4clip)
        txt_dataset = FashionEvalDataset(txt4eval)

        print("Calculating CLIP Score...")
        clip_score = eval_utils.calculate_clip_score_given_data(
            gen_dataset_clip,
            txt_dataset,
            batch_size=args.batch_size,
            device=device,
            num_workers=num_workers
        )
        torch.cuda.empty_cache()

        all_eval_metrics[ckpt]["CLIP score"] = clip_score
        np.save(eval_save_path, np.array(all_eval_metrics))

        print("Calculating Grd CLIP Score...")
        grd_clip_score = eval_utils.calculate_clip_score_given_data(
            grd_dataset_clip,
            txt_dataset,
            batch_size=args.batch_size,
            device=device,
            num_workers=num_workers
        )
        torch.cuda.empty_cache()

        all_eval_metrics[ckpt]["Grd CLIP score"] = grd_clip_score
        np.save(eval_save_path, np.array(all_eval_metrics))

        del txt4eval

        print("Calculating CLIP Image Score...")
        clip_img_score = eval_utils.calculate_clip_img_score_given_data(
            gen_dataset_clip,
            grd_dataset_clip,
            batch_size=args.batch_size,
            device=device,
            num_workers=num_workers,
            similarity_func=args.sim_func
        )
        torch.cuda.empty_cache()

        all_eval_metrics[ckpt]["CLIP Image score"] = clip_img_score
        np.save(eval_save_path, np.array(all_eval_metrics))
        
        del gen4clip
        del grd4clip

        # -------------------------------------------------------------- #
        #                       Calculating LPIPS                        #
        # -------------------------------------------------------------- #
        gen_dataset_lpips = FashionEvalDataset(gen4lpips)
        grd_dataset_lpips = FashionEvalDataset(grd4lpips)

        print("Calculating LPIP Score...")
        lpip_score = eval_utils.calculate_lpips_given_data(
            gen_dataset_lpips,
            grd_dataset_lpips,
            batch_size=args.batch_size,
            device=device,
            num_workers=num_workers,
            use_net=args.lpips_net
        )
        torch.cuda.empty_cache()

        all_eval_metrics[ckpt]["LPIP score"] = lpip_score
        np.save(eval_save_path, np.array(all_eval_metrics))
        
        del gen4lpips
        del grd4lpips

        # -------------------------------------------------------------- #
        #                  Evaluating Personalization                    #
        # -------------------------------------------------------------- #

        print("Evaluating Personalization of similarity...")
        # The similarity between history and generated images
        gen4personal_sim = {}
        gen4personal_sim["gen"] = []
        gen4personal_sim["hist"] = []
        for uid in gen_data:
            for oid in gen_data[uid]:
                for i, gen_idx in enumerate(gen_data[uid][oid]["images"]):
                    cate = gen_data[uid][oid]["cates"][i].item()
                    try:
                        gen4personal_sim["hist"].append(history[int(uid)][cate])
                        
                        gen_idx = gen_idx.item()
                        gen_iid = fitb_candidates[int(uid)][int(oid)][gen_idx]
                        gen_im = img_dataset[gen_iid]
                        gen4personal_sim["gen"].append(img_trans(gen_im))
                    except:
                        continue
                        gen4personal_sim["hist"].append(history['null'])
        
        gen_dataset_personal_sim = FashionPersonalSimDataset(gen4personal_sim)
        personal_sim_score = eval_utils.evaluate_personalization_given_data_sim(
            gen4eval=gen_dataset_personal_sim,
            batch_size=args.batch_size,
            device=device,
            num_workers=num_workers,
            similarity_func=args.sim_func
        )
        torch.cuda.empty_cache()

        all_eval_metrics[ckpt]["Personal Sim"] = personal_sim_score
        np.save(eval_save_path, np.array(all_eval_metrics))

        del gen4personal_sim

        # -------------------------------------------------------------- #
        #                   Evaluating Compatibility                     #
        # -------------------------------------------------------------- #
        print("Evaluating Compatibility...")
        outfits = []
        grd_outfits = []
        for uid in gen_data:
            for oid in gen_data[uid]:
                outfit = torch.tensor(fitb_test_dict[int(uid)][int(oid)])
                grd_outfit = torch.tensor(fitb_test_dict[int(uid)][int(oid)])
                fill_idxes = torch.nonzero(outfit == 0).cpu().numpy()
                for i,gen_idx in enumerate(gen_data[uid][oid]["images"]):
                    gen_idx = gen_idx.item()
                    gen_iid = fitb_candidates[int(uid)][int(oid)][gen_idx]
                    grd_iid = fitb_candidates[int(uid)][int(oid)][0]
                    outfit[fill_idxes[i]] = gen_iid
                    grd_outfit[fill_idxes[i]] = grd_iid

                real_grd_outfit = test_grd[int(oid)]["outfits"]
                assert grd_outfit.numpy().tolist() == real_grd_outfit

                outfits.append(outfit)
                grd_outfits.append(grd_outfit)
        
        outfits = torch.stack(outfits)
        outfit_dataset = FashionEvalDataset(outfits)
        grd_outfits = torch.stack(grd_outfits)
        grd_outfit_dataset = FashionEvalDataset(grd_outfits)

        gen_imgs = None
        cnn_feat_path = os.path.join(args.data_path, "cnn_features_clip.npy")
        cnn_feat_gen_path = os.path.join(eval_path, f"{args.task}-checkpoint-{ckpt}-cnnfeat.npy")
        compatibility_score, grd_compatibility_score = eval_utils.evaluate_compatibility_given_data(
            outfit_dataset,
            grd_outfit_dataset,
            gen_imgs,
            cnn_feat_path,
            cnn_feat_gen_path,
            args.pretrained_evaluator_ckpt,
            batch_size=args.batch_size,
            device=device,
            num_workers=num_workers
        )
        torch.cuda.empty_cache()

        all_eval_metrics[ckpt]["Compatibility"] = compatibility_score
        all_eval_metrics[ckpt]["Grd Compatibility"] = grd_compatibility_score
        np.save(eval_save_path, np.array(all_eval_metrics))

        del outfits
        del grd_outfits

        print("-" * 10 + f"{args.eval_version}-checkpoint-{str(ckpt)}-Grounding" + "-" * 10)
        print()
        print("## Fidelity ##")
        print(" " * 2 + f"[CLIP score]: {clip_score:.2f}")
        print(" " * 2 + f"[Grd CLIP score]: {grd_clip_score:.2f}")
        print(" " * 2 + f"[CLIP image score]: {clip_img_score:.2f}")
        print(" " * 2 + f"[LPIP Score]: {lpip_score:.2f}")
        print()
        print("## Personalization ##")
        print(" " * 2 + f"[Personal Sim]: {personal_sim_score:.2f}")
        print()
        print("## Compatibility ##")
        print(" " * 2 + f"[Compatibility score]: {compatibility_score:.2f}")
        print(" " * 2 + f"[Grd Compatibility score]: {grd_compatibility_score:.2f}")
        print()
        print("## Retrieval Accuracy ##")
        print(" " * 2 + f"[CLIP Accuracy]: {clip_acc:.2f}")
        print()
        print()

    print(f"All the ckpts of {args.eval_version} have been evaluated: {ckpts}")
    print(all_eval_metrics)
    print(f"Successfully saved evaluation results of {args.eval_version} checkpoint-{ckpts} to {eval_save_path}.")

def set_random_seed(seed=0):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

if __name__ == '__main__':
    main()
