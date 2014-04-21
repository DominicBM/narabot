#! /usr/bin/env python

from __future__ import print_function
import os, subprocess, sys

def make_djvu(infile, outdir):
    outfile = outdir.join
    subprocess.call(["c44", infile, outfile])
    print("Converting {0} => {1}".format(infile, outfile))

if __name__ == "__main__":
    path = sys.argv[1]
    print(os.listdir(path))
    for root, dirs, files in os.walk(path):
        # prune files and directories beginning with dot
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        files[:] = [f for f in files if not f.startswith('.')]
    for x in files:
        print(x)
    
    
    #try:
    #    args = getopt.getopt(sys.argv[1:], "")
    #    if len(args) == 1:
    #        print('using glob')
    #        args = glob.glob(args[0])
    #        args.sort()
    #    i = 0
    #    while i < len(args):
    #        make_djvus(args[i])
    #        i = i + 1  
    #except getopt.error, msg:
    #    print(msg)
    #    print("This program has no options")
    #    sys.exit(2)