import os
import argparse
import subprocess
import shutil
import glob
import json
import re
import time
import atexit
import hashlib
from typing import List
import tqdm
from dataclasses import dataclass
from colorama import init, Fore

@dataclass
class VideoData:
    tempPath : str
    videoPath : str
    rifePath : str
    productPath : str
    ffmpegPath : str
    ffprobePath : str
    imdiskPath : str
    portion : int
    exp : int
    model : str
    ffmpegArgs : List[str]

class VideoInfomation():
    def __init__(self, vPath, portion, ffprobePath):
        self.vPath = vPath
        self.portion = portion
        self.ffprobePath = ffprobePath
        self.getVideoInfo()
        self.sectionLength = self.framesCount // self.portion
        self.lastSectionLength = self.framesCount % self.portion
    def getBeginTime(self, portion):
        if portion > self.portion:
            return None
        else:
            return self.sectionLength * portion
    def getDurtion(self, portion):
        if portion == self.portion:
            return self.lastSectionLength
        else:
            return self.sectionLength
    def getVideoInfo(self):
        res = subprocess.run(args=[self.ffprobePath, "-i", self.vPath, "-show_streams", "-select_streams", "v", "-print_format", "json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        info = json.loads(res.stdout.decode("utf-8"))["streams"][0]
        self.framesCount = int(info["nb_frames"])
        self.fps = eval(info["r_frame_rate"])

class VideoExtract():
    def __init__(self, extPath, video, ffmpeg):
        self.extPath = extPath
        self.video = video
        self.ffmpegPath = ffmpeg

        os.makedirs(self.extPath, exist_ok=True)
    def extVideo(self, portion):
        pbar = tqdm.tqdm(total=self.video.getDurtion(portion), colour="magenta", desc="Extracting the video", leave=False, unit="img", position=2)
        process = subprocess.Popen(args=[self.ffmpegPath, "-i", self.video.vPath, "-vf", 
                             f"select=between(n\,{int(self.video.getBeginTime(portion))}\,{int(self.video.getBeginTime(portion) + self.video.getDurtion(portion) - 1)}), setpts=PTS-STARTPTS",
                            "-y", "-hide_banner", os.path.join(self.extPath, "%08d.png")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", text=True)
        for line in process.stdout:
            result = re.search(r'frame=\s*(.*?) .*', line)
            if result is not None:
                currentFrame = int(result.group(1))
                #print(f"Extracting the video: {currentFrame / self.video.getDurtion(portion):.2%} CurrentFrame: {currentFrame}")
                pbar.update(currentFrame - pbar.n)
        
        pbar.close()

        process.wait()
        if process.poll():
            print(Fore.RED + f"Error:\n{process.stdout}")

    def extAudio(self):
        subprocess.run(args=[self.ffmpegPath, "-i", self.video.vPath, "-vn", "-y", "-acodec", "copy",
                            os.path.abspath(os.path.join(self.extPath, os.pardir, f"{os.path.basename(self.video.vPath)}.m4a"))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def clearPath(self):
        shutil.rmtree(self.extPath)
        os.makedirs(self.extPath, exist_ok=True)

class rifeProcess():
    def __init__(self, rPath, iPath, oPath, exp, model, video):
        self.rPath = rPath
        self.iPath = iPath
        self.oPath = oPath
        self.exp = exp
        self.model = model
        self.video = video

        os.makedirs(oPath, exist_ok=True)
    def run(self, portion):
        frames = self.exp * self.video.getDurtion(portion)
        pbar = tqdm.tqdm(total=frames, colour="yellow", desc="Video frame interpolating", leave=False, unit="img", position=2)
        process = subprocess.Popen(args=[self.rPath, "-i", self.iPath, "-o", self.oPath, 
                             "-n", str(frames), "-m", self.model], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", text=True)
        while (currentFile := self.getFileNum()) != frames:
            #print(f"Video frame interpolating: {currentFile / frames:.2%} CurrentFrames: {currentFile}")
            pbar.update(currentFile - pbar.n)
            time.sleep(1)
        
        pbar.close()

        process.wait()
        if process.poll():
            print(Fore.RED + f"Error:\n{process.stdout}")
        
    def clearPath(self):
        shutil.rmtree(self.oPath)
        os.makedirs(self.oPath, exist_ok=True)

    def getFileNum(self):
        return len(os.listdir(self.oPath))

class VideoEncode():
    def __init__(self, iPath, oPath, exp, video, ffmpeg, settings):
        self.iPath = iPath
        self.oPath = oPath
        self.exp = exp
        self.video = video
        self.ffmpegPath = ffmpeg
        self.settings = settings

        os.makedirs(oPath, exist_ok=True)
    def run(self, portion):
        pbar = tqdm.tqdm(total=self.video.getDurtion(portion) * self.exp, colour="blue", desc="Encoding the video", leave=False, unit="img", position=2)
        process = subprocess.Popen(args=[self.ffmpegPath, "-framerate", str(self.video.fps * self.exp), "-i", os.path.join(self.iPath, "%08d.png"), "-y", "-hide_banner", *self.settings,   
                                   f"{os.path.join(self.oPath, str(portion) + '.ts')}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", text=True)
        for line in process.stdout:
            result = re.search(r'frame=\s*(.*?) .*', line)
            if result is not None:
                currentFrame = int(result.group(1))
                #print(f"Encoding the video: {currentFrame / (self.video.getDurtion(portion) * self.exp):.2%} CurrentFrame: {currentFrame}")
                pbar.update(currentFrame - pbar.n)
        
        pbar.close()      
                
        process.wait()
        if process.poll():
            print(Fore.RED + f"Error:\n{process.stdout}")
    def generateList(self):
        with open(os.path.join(self.oPath, "concat.txt"), "w") as f:
            for i in range(0, self.video.portion + 1):
                f.write(f"file '{os.path.join(os.path.abspath(self.oPath), str(i) + '.ts')}'\n")

class VideoConcat():
    def __init__(self, iPath, oPath, video, ffmpeg):
        self.iPath = iPath
        self.oPath = oPath
        self.video = video
        self.ffmpegPath = ffmpeg

        os.makedirs(oPath, exist_ok=True)
    def run(self):
        subprocess.run(args=[self.ffmpegPath, "-f", "concat", "-safe", "0", "-y", "-i", os.path.join(self.iPath, "concat.txt"),
                             "-i", os.path.abspath(os.path.join(self.iPath, os.pardir, f"{os.path.basename(self.video.vPath)}.m4a")),
                             "-c", "copy", os.path.join(self.oPath, f"processed_{os.path.basename(self.video.vPath)}")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def clearPath(self):
        shutil.rmtree(self.iPath)
        os.makedirs(self.iPath, exist_ok=True)

class manager():
    def __init__(self, data):
        self.data = data
    def run(self):
        if os.path.isdir(self.data.videoPath):
            videoList = [v for v in glob.glob(os.path.join(self.data.videoPath, "*.mp4"))]
        else:
            videoList = [self.data.videoPath]

        for video in tqdm.tqdm(videoList, desc="Processing File", colour="cyan", position=0):
            videoInfo = VideoInfomation(video, self.data.portion, self.data.ffprobePath)
            extractor = VideoExtract(os.path.join(self.data.tempPath, "input_frames"), videoInfo, self.data.ffmpegPath)
            rife = rifeProcess(self.data.rifePath, os.path.join(self.data.tempPath, "input_frames"), 
                               os.path.join(self.data.tempPath, "output_frames"), self.data.exp,
                               self.data.model, videoInfo)
            encoder = VideoEncode(os.path.join(self.data.tempPath, "output_frames"), os.path.join(self.data.tempPath, "output_ts"),
                                  self.data.exp, videoInfo, self.data.ffmpegPath, self.data.ffmpegArgs)
            concat = VideoConcat(os.path.join(self.data.tempPath, "output_ts"), self.data.productPath, videoInfo, self.data.ffmpegPath)
            extractor.clearPath()
            rife.clearPath()
            concat.clearPath()

            pbar = tqdm.tqdm(range(0, self.data.portion + 1), desc="Total Portion", colour="green", position=1)
            for i in pbar:
                #print(Fore.YELLOW + f"{i} / {self.data.portion} portion, extracting the video. eta {i / self.data.portion:.2%}")
                os.system(f"title {i + 1} / {self.data.portion + 1} portion, extracting the video. eta {i / self.data.portion:.2%}")
                extractor.extVideo(i)
                #print(Fore.YELLOW + f"{i} / {self.data.portion} portion, video frame interpolating. eta {i / self.data.portion:.2%}")
                os.system(f"title {i + 1} / {self.data.portion + 1} portion, video frame interpolating. eta {i / self.data.portion:.2%}")
                rife.run(i)
                #print(Fore.YELLOW + f"{i} / {self.data.portion} portion, encoding the video. eta {i / self.data.portion:.2%}")
                os.system(f"title {i + 1} / {self.data.portion + 1} portion, encoding the video. eta {i / self.data.portion:.2%}")
                encoder.run(i)
                extractor.clearPath()
                rife.clearPath()

            os.system("title Concating the video.")
            print(Fore.YELLOW + "Concating the video.")
            encoder.generateList()
            extractor.extAudio()
            concat.run()
            concat.clearPath()
            os.system("title Task completed.")
            print(Fore.GREEN + "Task completed.")

    @staticmethod
    def getmd5(path):
        with open(path, "rb") as f:
            file_hash = hashlib.md5()
            while chunk := f.read(8192):
                file_hash.update(chunk)
        return file_hash.hexdigest()

if __name__ == "__main__":
    init(autoreset=True)
    parser = argparse.ArgumentParser(description="A program used to automatically process video frame interpolation.")
    parser.add_argument("-i", "--input" ,help="A directory or a single video file which must be mp4", required=True, type=str)
    parser.add_argument("-e", "--exp", help="The times multiplied by the current fps", required=True, type=int)
    parser.add_argument("-p", "--portion", help="How many portions the video will be divided", type=int, default=5)
    parser.add_argument("-o", "--output", help="The directory where the result will be placed", type=str, default="result")
    parser.add_argument("--temp", help="The temporary directory", type=str, default="temp")
    parser.add_argument("--ffmpeg", help="The directory where ffmpeg.exe is placed", type=str, default="tools/ffmpeg.exe")
    parser.add_argument("--ffprobe", help="The directory where ffprobe.exe is placed", type=str, default="tools/ffprobe.exe")
    parser.add_argument("--rife", help="The directory where ncnn_rife is placed", type=str, default="tools/rife/rife-ncnn-vulkan.exe")
    parser.add_argument("--model", help="The model which rife will use", type=str, default="rife-v4.6")
    parser.add_argument("--ffmpegArgs", help="The args will pass through ffmpeg when encoding. Default use crf 15 & libx264", nargs=argparse.REMAINDER, default=["-crf", "15", "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    
    args = parser.parse_args()
    data = VideoData(
        tempPath=args.temp,
        ffmpegPath=args.ffmpeg,
        ffprobePath=args.ffprobe,
        rifePath=args.rife,
        imdiskPath="",
        model=args.model,

        videoPath=args.input,
        productPath=args.output,
        portion=args.portion,
        exp=args.exp,

        ffmpegArgs = args.ffmpegArgs #encoder="h264_nvenc"
        )

    m = manager(data)
    m.run()