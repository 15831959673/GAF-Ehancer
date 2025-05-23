import sys
import random
from deap import creator, base, tools, algorithms
import numpy as np
import copy
from tqdm import tqdm
import copy
from os.path import splitext, exists, dirname, join, basename
import os
import argparse
import oracle
import torch
from torch.utils.data import DataLoader, TensorDataset

print(torch.cuda.current_device())
randomizer = np.random

# Default values
DEFAULT_SEQUENCE_LENGTH = 249
DEFAULT_NUCLEOTIDE_FREQUENCY = [0.25, 0.25, 0.25, 0.25]
DEFAULT_SEED = 12345
DEFAULT_BEST_MODEL_CHECKPOINT = "checkpoint_keras"
DEFAULT_INDPB = 0.025
DEFAULT_POPULATION_SIZE = 1000
DEFAULT_NGEN = 90
DEFAULT_OUTPUT_FILE = "evolution_fits_df.csv"
device = torch.device("cuda:0")

# Command line argument parsing
parser = argparse.ArgumentParser(description='Evolutionary Algorithm for DNA Sequences')
parser.add_argument('--sequence_length', type=int, default=DEFAULT_SEQUENCE_LENGTH,
                    help='Length of DNA sequences')
parser.add_argument('--nucleotide_frequency', type=float, nargs=4, default=DEFAULT_NUCLEOTIDE_FREQUENCY,
                    help='Nucleotide frequencies [A, C, G, T]')
parser.add_argument('--seed', type=int, default=DEFAULT_SEED,
                    help='Random seed for numpy and TensorFlow')
parser.add_argument('--best_model_checkpoint', type=str, default=DEFAULT_BEST_MODEL_CHECKPOINT,
                    help='Path to the best model checkpoint')
parser.add_argument('--indpb', type=float, default=DEFAULT_INDPB,
                    help='Mutation probability')
parser.add_argument('--n', type=int, default=DEFAULT_POPULATION_SIZE,
                    help='Initial population size')
parser.add_argument('--NGEN', type=int, default=DEFAULT_NGEN,
                    help='Number of generations for optimization')
parser.add_argument('--output_file', type=str, default=DEFAULT_OUTPUT_FILE,
                    help='Output file path for evolution fitness dataframe CSV')
args = parser.parse_args()

# Setting random seed
torch.manual_seed(args.seed)
random.seed(args.seed)
np.random.seed(args.seed)

# Setting CUDA visible devices
os.environ["CUDA_VISIBLE_DEVICES"] = "0"


# Load best model
best_model = oracle.get_gosai_oracle(mode='eval').to(device)


# DNA one-hot encoding class
class DNAoneHotEncoding:
    """
    DNA sequences one hot encoding
    """

    def __call__(self, sequence: str):
        assert (len(sequence) > 0)
        encoding = np.zeros((len(sequence), 4), dtype="float32")
        A = np.array([1, 0, 0, 0])
        C = np.array([0, 1, 0, 0])
        G = np.array([0, 0, 1, 0])
        T = np.array([0, 0, 0, 1])
        for index, nuc in enumerate(sequence):
            if nuc == "A":
                encoding[index, :] = A
            elif nuc == "C":
                encoding[index, :] = C
            elif nuc == "G":
                encoding[index, :] = G
            elif nuc == "T":
                encoding[index, :] = T
        return encoding


# Fitness function evaluation
def fitness(dna_population: list):
    onehot_encoding = DNAoneHotEncoding()
    dna_dataset = ["".join(dna_list) for dna_list in dna_population]
    dna_encoding = torch.tensor(np.stack([onehot_encoding(dna) for dna in dna_dataset])).permute(0, 2, 1).to(device)
    dataset = TensorDataset(dna_encoding)
    dataloader = DataLoader(dataset, batch_size=32, shuffle=False)
    predict_fitness = np.array([])
    # 使用 tqdm 为 DataLoader 添加进度条
    for batch in dataloader:
        batch_data = batch[0]  # 因为我们只有一个输入，batch[0] 就是 dna_encoding 的当前批次
        predictions = best_model(batch_data).cpu().detach().numpy()  # 使用 best_model 进行预测
        if predict_fitness.size == 0:
            predict_fitness = predictions
        else:
            # 否则将当前批次的 predictions 按照批次维度堆叠到 predict_fitness 中
            predict_fitness = np.concatenate((predict_fitness, predictions), axis=0)
    if isinstance(predict_fitness, np.ndarray) and predict_fitness.shape[1] == 2:
        return [(i,) for i in predict_fitness.squeeze()[:, 0].tolist()]
    else:
        # predict_fitness = np.stack(predict_fitness).squeeze().T[:, 0]
        return [(i,) for i in predict_fitness.squeeze().tolist()]


# Mutation function
def mutation(individual, indpb):
    for i in range(len(individual)):
        if random.random() < indpb:
            if individual[i] == 'A':
                individual[i] = (randomizer.choice(list('CGT'), p=[
                    args.nucleotide_frequency[1] / (1 - args.nucleotide_frequency[0]),
                    args.nucleotide_frequency[2] / (1 - args.nucleotide_frequency[0]),
                    args.nucleotide_frequency[3] / (1 - args.nucleotide_frequency[0])]))
            elif individual[i] == 'C':
                individual[i] = (randomizer.choice(list('AGT'), p=[
                    args.nucleotide_frequency[0] / (1 - args.nucleotide_frequency[1]),
                    args.nucleotide_frequency[2] / (1 - args.nucleotide_frequency[1]),
                    args.nucleotide_frequency[3] / (1 - args.nucleotide_frequency[1])]))
            elif individual[i] == 'G':
                individual[i] = (randomizer.choice(list('CGT'), p=[
                    args.nucleotide_frequency[2] / (1 - args.nucleotide_frequency[2]),
                    args.nucleotide_frequency[1] / (1 - args.nucleotide_frequency[2]),
                    args.nucleotide_frequency[3] / (1 - args.nucleotide_frequency[2])]))
            elif individual[i] == 'T':
                individual[i] = (randomizer.choice(list('CGT'), p=[
                    args.nucleotide_frequency[0] / (1 - args.nucleotide_frequency[3]),
                    args.nucleotide_frequency[1] / (1 - args.nucleotide_frequency[3]),
                    args.nucleotide_frequency[2] / (1 - args.nucleotide_frequency[3])]))
    return individual,


# Random sequence generator
def random_sequence_generator(randomizer, args):
    return randomizer.choice(list('ACGT'), p=args.nucleotide_frequency)


def train(existing_population):
    # DEAP Toolbox initialization
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    creator.create("Individual", list, fitness=creator.FitnessMax)
    toolbox = base.Toolbox()
    toolbox.register("base", random_sequence_generator, randomizer, args)
    toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.base, n=args.sequence_length)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", fitness)
    toolbox.register("mate", tools.cxTwoPoint)
    toolbox.register("mutate", mutation, indpb=args.indpb)
    toolbox.register("select", tools.selTournament, tournsize=3)

    # Population initialization
    population = [creator.Individual(ind) for ind in existing_population]
    # population = toolbox.population(n=args.n)
    NGEN = args.NGEN

    # Evolutionary algorithm loop
    evolution_fits = {
        "generation": [],
        "fitness": [],
        "sequences": [],
        "id": []
    }

    for gen in tqdm(range(NGEN)):
        offspring = algorithms.varAnd(population, toolbox, cxpb=0.01, mutpb=0.01)
        fits = toolbox.evaluate(offspring)
        id = 0
        for fit, ind in zip(fits, offspring):
            ind.fitness.values = fit
            evolution_fits["fitness"].append(fit[0])
            evolution_fits["generation"].append(gen)
            evolution_fits["sequences"].append("".join(ind))
            evolution_fits["id"].append(id)
            id = id + 1
        population = toolbox.select(offspring, k=len(population))

    # Selecting top 10 individuals
    top10 = tools.selBest(population, k=10)

    # Saving evolution data to CSV
    import pandas as pd
    evolution_fits_df = pd.DataFrame(evolution_fits)
    evolution_fits_df.to_csv(args.output_file, index=False)

    return evolution_fits['sequences'], evolution_fits['fitness']
