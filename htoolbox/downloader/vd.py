import argparse
import multiprocessing as mp
import os
import os.path as osp
import re
import time
import urllib.request

import rich
import rich.progress
import wget
from rich.progress import Progress


def parse_args():
    parser = argparse.ArgumentParser(description="Download videos listed in a file.")
    parser.add_argument(
        "-u",
        "--urls",
        default="urls.txt",
        help="Path to the newline-delimited URL list.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Directory to store downloads.",
    )
    parser.add_argument(
        "-j",
        "--num_processes",
        type=int,
        default=5,
        help="Number of worker processes.",
    )
    return parser.parse_args()


class Video:
    def __init__(self, name: str, url, ctime, download_dir, path=None):
        self.name = name
        self.ctime = ctime
        self.filename = name if name.endswith(".mp4") else name + ".mp4"
        self.url = url
        self.download_dir = download_dir
        self.path = path or osp.join(self.download_dir, self.filename)

    def exists(self):
        return osp.exists(self.path)

    def complete(self):
        resp = urllib.request.urlopen(self.location)
        length = int(resp.getheader("content-length"))
        resp.close()
        return self.exists() and os.stat(self.path).st_size == length

    def download(self, _progress, task_id):
        if not osp.exists(osp.dirname(self.path)):
            return

        def bar(current, total, width=80):
            _progress[task_id] = {"progress": current, "total": total}

        try:
            wget.download(self.url, self.path, bar=bar)
            os.utime(self.path, (self.ctime, self.ctime))
        except Exception as e:
            print(f"An error occurred: {e}")

    def __repr__(self):
        return f"| {self.name} | {self.url} |"


def download_one(video, progress, task_id):
    video.download(progress, task_id)


class MyProgress(Progress):
    def get_renderables(self):
        for task in self.tasks:
            if task.fields.get("progress_type") == "overview":
                self.columns = (
                    "[progress.description]{task.description}",
                    rich.progress.BarColumn(),
                    "{task.completed}/{task.total}",
                    rich.progress.TimeElapsedColumn(),
                )
            if task.fields.get("progress_type") == "task":
                self.columns = (
                    "[progress.description]{task.description}",
                    rich.progress.BarColumn(),
                    rich.progress.DownloadColumn(),
                    rich.progress.TransferSpeedColumn(),
                    rich.progress.TimeElapsedColumn(),
                )
            yield self.make_tasks_table([task])


def get_urls_to_download(urls_path):
    with open(urls_path, "r", encoding="utf-8") as file_obj:
        content = file_obj.read()
    urls = content.strip("\n\r\t ").split("\n")
    urls = [u for u in urls if u != ""]
    return urls


def find_last_video_id(dirname):
    files = os.listdir(dirname)
    files = filter(lambda f: re.match(r"\d{4}.mp4", f), files)
    files = sorted(files)
    if len(files) == 0:
        last_id = 0
    else:
        last_id = int(re.match(r"(\d{4}).mp4", files[-1]).group(1))
    return last_id


def main():
    args = parse_args()
    os.makedirs(args.output, exist_ok=True)
    last_id = find_last_video_id(args.output)
    urls = get_urls_to_download(args.urls)
    jobs = [(url, f"{last_id + 1 + i:04d}") for i, url in enumerate(urls)]

    with MyProgress() as progress, mp.Manager() as manager:
        _progress = manager.dict()
        overall_progress_task = progress.add_task("[green]All jobs progress:", progress_type="overview")
        pool = mp.Pool(processes=args.num_processes)
        results = []
        tasks = []
        for url, name in jobs:
            video = Video(name, url, ctime=time.time(), download_dir=args.output)
            time.sleep(0.5)
            task_id = progress.add_task(video.name, visible=False, progress_type="task")
            tasks.append((video, task_id))
            result = pool.apply_async(download_one, (video, _progress, task_id))
            results.append(result)
        pool.close()

        ready_count = 0
        while ready_count < len(results):
            ready_count = 0
            for result in results:
                if result.ready():
                    ready_count += 1
            progress.update(overall_progress_task, completed=ready_count, total=len(results))
            for task_id, update_data in _progress.items():
                latest = update_data["progress"]
                total = update_data["total"]
                progress.update(
                    task_id,
                    completed=latest,
                    total=total,
                    visible=latest < total,
                )
            time.sleep(1)
        pool.join()


if __name__ == "__main__":
    main()
