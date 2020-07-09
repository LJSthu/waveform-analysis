#!/usr/bin/env python3
import argparse
psr = argparse.ArgumentParser()
psr.add_argument('ipt', help='input file')
psr.add_argument('opt', help='output file')
psr.add_argument('NetDir', help='Network directory')
psr.add_argument('-B', '--batchsize', dest='BAT', type=int, default=15000)
psr.add_argument('-D', '--device', dest='Device', type=str, default='cpu')
args = psr.parse_args()
NetDir = args.NetDir
output = args.opt
filename = args.ipt
BATCHSIZE = args.BAT
Device = args.Device

import time
global_start = time.time()
cpu_global_start = time.clock()
import numpy as np
import tables
import pandas as pd
from tqdm import tqdm

import torch
from torch.nn import functional as F

from multiprocessing import Pool
from JPwaptool import JPwaptool

from IPython import embed

# Loading Data
RawDataFile = tables.open_file(filename, "r")
WaveformTable = RawDataFile.root.Waveform
origin_dtype = WaveformTable.dtype
WindowSize = origin_dtype["Waveform"].shape[0]
gpufloat_dtype = np.dtype([(name, np.dtype('float32') if name == "Waveform" else origin_dtype[name].base, origin_dtype[name].shape) for name in origin_dtype.names])
Total_entries = len(WaveformTable)
print("Initialization finished, real time {0:.4f}s, cpu time {1:.4f}s".format(time.time() - global_start, time.clock() - cpu_global_start))
print("Processing {} entries".format(Total_entries))


def Read_Data(startentry, endentry) :
    Waveforms_and_info = WaveformTable[startentry:endentry]
    Shifted_Waves_and_info = np.empty(Waveforms_and_info.shape, dtype=gpufloat_dtype)
    for name in origin_dtype.names :
        if name != "Waveform" :
            Shifted_Waves_and_info[name] = Waveforms_and_info[name]
    if WindowSize >= 1000 :
        stream = JPwaptool(WindowSize, 100, 600)
    elif WindowSize == 600 :
        stream = JPwaptool(WindowSize, 50, 400)
    else:
        raise ValueError("Unknown WindowSize, I don't know how to choose the parameters for pedestal calculatation")
    for i, w in enumerate(Waveforms_and_info["Waveform"]) :
        stream.FastCalculate(w)
        Shifted_Waves_and_info[i]["Waveform"] = stream.ChannelInfo.Ped - w
    return pd.DataFrame({name: list(Shifted_Waves_and_info[name]) for name in gpufloat_dtype.names})


N = 10
tic = time.time()
cpu_tic = time.clock()
if N == 1 :
    Waveforms_and_info = Read_Data(0, Total_entries)
else :
    slices = np.append(np.arange(0, Total_entries, int(np.ceil(Total_entries / N))), Total_entries)
    ranges = list(zip(slices[0:-1], slices[1:]))
    with Pool(N) as pool :
        Waveforms_and_info = pd.concat(pool.starmap(Read_Data, ranges))
print("Data Loaded, consuming {0:.4f}s using {1} threads, cpu time {2:.4f}s".format(time.time() - tic, N, time.clock() - cpu_tic))

channelid_set = set(Waveforms_and_info['ChannelID'])
Channel_Grouped_Waveform = Waveforms_and_info.groupby(by="ChannelID")

# Loading CNN Net
tic = time.time()
if Device.isdigit() :
    Device = int(Device)
device = torch.device(Device)
nets = dict([])
for channelid in tqdm(channelid_set, desc="Loading Nets of each channel") :
    nets[channelid] = torch.load(NetDir + "/Channel{}.torch_net".format(channelid), map_location=device)
print("Net Loaded, consuming {0:.4f}s".format(time.time() - tic))


filter_limit = 0.9 / WindowSize
Timeline = torch.arange(WindowSize, device=device)


def Forward(channelid) :
    Data_of_this_channel = Channel_Grouped_Waveform.get_group(channelid)
    Shifted_Wave = np.vstack(Data_of_this_channel['Waveform'])
    EventIDs = np.array(Data_of_this_channel['EventID'])
    PETimes = np.empty(0, dtype=np.int16)
    Weights = np.empty(0, dtype=np.float32)
    EventData = np.empty(0, dtype=np.int64)
    slices = np.append(np.arange(0, len(Shifted_Wave), BATCHSIZE,), len(Shifted_Wave))
    for i in range(len(slices) - 1) :
        inputs = torch.from_numpy(Shifted_Wave[slices[i]:slices[i + 1]])
        Prediction = nets[channelid].forward(inputs.to(device=device)).data
        PETime = Prediction > filter_limit
        pe_numbers = PETime.sum(1)
        no_pe_found = (pe_numbers == 0)
        if no_pe_found.any() :
            print("I cannot find any pe in Event {0}, Channel {1}".format(EventIDs[slices[i]:slices[i + 1]][no_pe_found.cpu().numpy()], channelid))
            guessed_petime = F.relu(inputs[no_pe_found].max(1)[1] - 7)
            PETime[no_pe_found, guessed_petime] = True
            Prediction[no_pe_found, guessed_petime] = 1
            pe_numbers[no_pe_found] = 1
        Weights = np.append(Weights, Prediction[PETime].cpu().numpy())
        TimeMatrix = Timeline.repeat([len(PETime), 1])[PETime]
        PETimes = np.append(PETimes, TimeMatrix.cpu().numpy())
        pe_numbers = pe_numbers.cpu().numpy()
        EventData = np.append(EventData, np.repeat(EventIDs[slices[i]:slices[i + 1]], pe_numbers))
        ChannelData = np.empty(EventData.shape, dtype=np.int16)
        ChannelData.fill(channelid)
    return pd.DataFrame({"PETime": PETimes, "Weight": Weights, "EventID": EventData, "ChannelID": ChannelData})


tic = time.time()
cpu_tic = time.clock()
Result = []
embed()
for ch in tqdm(channelid_set, desc="Predict for each channel") :
    Result.append(Forward(ch))
Result = pd.concat(Result)
Result = Result.sort_values(by=["EventID", "ChannelID"])
print("Prediction generated, real time {0:.4f}s, cpu time {1:.4f}s".format(time.time() - tic, time.clock() - cpu_tic))

embed()

class AnswerData(tables.IsDescription):
    EventID = tables.Int64Col(pos=0)
    ChannelID = tables.Int16Col(pos=1)
    PETime = tables.Int16Col(pos=2)
    Weight = tables.Float32Col(pos=3)


AnswerFile = tables.open_file(output, mode="w", title="OneTonDetector", filters=tables.Filters(complevel=4))
AnswerTable = AnswerFile.create_table("/", "Answer", AnswerData, "Answer")
AnswerTable.append([Result[name].to_numpy() for name in AnswerTable.colnames])
AnswerTable.flush()
AnswerFile.close()
RawDataFile.close()
print("Finished! Consuming {0:.2f}s in total, cpu time {1:.2f}s.".format(time.time() - global_start, time.clock() - cpu_global_start))
