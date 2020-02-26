#!/usr/bin/python
'''
Written by Edo Liberty and Pavel Vesely. All rights reserved.
Intended for academic use only. No commercial use is allowed.
'''

import sys
#from random import random
from math import ceil
from numpy.random import random, geometric

class RelativeErrorSketch:
    def __init__(self, eps=0.01, schedule='deterministic', always=-1, never=-1, sectionSize=-1, initMaxSize=0, lazy=True, alternate=True):
        eps_lower_bound, eps_upper_bound = 1e-6, 0.5 #TODO remove?
        if eps < eps_lower_bound or eps > eps_upper_bound:
            raise ValueError(f"eps must be int the range [{eps_lower_bound}.{eps_upper_bound}]")
        self.eps = eps

        self.Compactor = RelativeCompactor

        self.lazy = lazy
        self.alternate = alternate
        self.schedule = schedule
        self.always = always
        self.never = never
        self.sectionSize = sectionSize
        
        self.initNumSections = 2 # an initial upper bound on log_2 of the number of compactions

        # default setting of sectionSize, always, and never according to eps
        if self.sectionSize == -1:
            self.sectionSize = 2*(int(1/(4*eps))+1) # ensured to be even and positive (thus >= 2)
        if self.always == -1:
            self.always = self.sectionSize

        self.neverGrows = False # if never is set by the user, then we do not let it grow
        if self.never == -1:
            self.never = self.sectionSize * self.initNumSections
            self.neverGrows = True

        self.compactors = []
        self.H = 0
        self.size = 0
        self.grow()
        
    def grow(self):
        self.compactors.append(self.Compactor(schedule=self.schedule, sectionSize=self.sectionSize, numSections=self.initNumSections, always=self.always, never=self.never, neverGrows=self.neverGrows, height=self.H, alternate=self.alternate))
        self.H = len(self.compactors)
        self.updateMaxSize()

    def updateMaxSize(self):
        self.maxSize = sum(c.capacity() for c in self.compactors) # a new bound for when to compress the sketch

    def update(self, item):
        self.compactors[0].append(item)
        self.size += 1
        if self.size >= self.maxSize:
            self.compress()
        assert(self.size < self.maxSize)
            
    def compress(self):
        self.updateMaxSize()
        if self.size < self.maxSize:
            return
        for h in range(len(self.compactors)):
            if len(self.compactors[h]) >= self.compactors[h].capacity():
                if h+1 >= self.H: self.grow()
                self.compactors[h+1].extend(self.compactors[h].compact())
                self.size = sum(len(c) for c in self.compactors)
                if(self.lazy and self.size < self.maxSize):
                    break
        debugPrint(f"compression done: size {self.size}\t maxSize {self.maxSize}")

    def merge(self, other):
        # Grow until self has at least as many compactors as other
        while self.H < other.H: self.grow()
        # Append the items in same height compactors 
        for h in range(other.H): self.compactors[h].extend(other.compactors[h])
        self.size = sum(len(c) for c in self.compactors)
        # Keep compressing until the size constraint is met
        while self.size >= self.maxSize:
            self.compress()
        assert(self.size < self.maxSize)
        
    def rank(self, value):
        return sum(c.rank(value)*2**h for (h, c) in enumerate(self.compactors))

    def quantile(self, rank):
        return "" #TODO

    # the following two fucntions are the same as in kll.py
    def cdf(self):
        itemsAndWeights = []
        for (h, items) in enumerate(self.compactors):
             itemsAndWeights.extend( (item, 2**h) for item in items )
        totWeight = sum( weight for (item, weight) in itemsAndWeights)
        itemsAndWeights.sort()
        cumWeight = 0
        cdf = []
        for (item, weight) in itemsAndWeights:
            cumWeight += weight
            cdf.append( (item, float(cumWeight)/float(totWeight) ) )
        return cdf
    
    def ranks(self):
        ranksList = []
        itemsAndWeights = []
        for (h, items) in enumerate(self.compactors):
             itemsAndWeights.extend( (item, 2**h) for item in items )
        itemsAndWeights.sort()
        cumWeight = 0
        for (item, weight) in itemsAndWeights:
            cumWeight += weight
            ranksList.append( (item, cumWeight) )
        return ranksList

    def __repr__(self):
        lengths = reversed([len(c) for c in self.compactors])
        return '\n'.join(['*'*l for l in lengths])


class RelativeCompactor(list):
    def __init__(self, **kwargs):
        self.numCompaction = 0
        self.offset = 0
        #self.eps = kwargs['eps']
        self.alternate = kwargs.get('alternate', True)
        self.sectionSize = kwargs.get('sectionSize', 32)
        self.numSections = kwargs.get('numSections', 2)
        self.always = kwargs.get('always', self.sectionSize)
        self.never = kwargs.get('never', self.sectionSize * self.numSections)
        self.neverGrows = kwargs.get('neverGrows', True)
        self.height = kwargs.get('height', 0) 
        self.schedule = kwargs.get('schedule', "deterministic")
        self.schedules = ['deterministic','randomized']
        assert(self.schedule in self.schedules)

    def compact(self):
        assert(len(self) >= self.capacity())
        
        self.sort()
        
        s = self.never # where the compaction starts; default is self.never
        secsToCompact = 0

        # choose a part to compact according to the selected schedule
        if self.sectionSize > 0:
            if self.schedule == 'randomized':
                while True:
                    secsToCompact = geometric(0.5)
                    if (secsToCompact <= self.numSections):
                        break
            else: #if self.schedule == 'deterministic' 
                secsToCompact = trailing_zeros(self.numCompaction)
            s = self.never + (self.numSections - secsToCompact) * self.sectionSize
                        
            # make the number of sections larger 
            if self.numCompaction > 2 * 2**self.numSections: #TODO 4 --> sth else?
                self.numSections *= 2 # basically, a doubling strategy on log_2 (number of compactions)
                if self.neverGrows:
                    self.never = self.sectionSize * self.numSections
            
        #TODO schedule randomizedSimple: set s uniformly and randomly in [0.25 * capacity(), 0.75 * capacity()], or sth like that
        
        if (len(self) - s)%2==1: # ensure that the compacted part has an even size
            if s > 0: s -= 1
            else: s += 1

        assert(s < len(self) - 1)
        
        # random offset for choosing odd/even items in the compacted part; if alternate, then random choice done every other time
        if (self.numCompaction%2==1 and self.alternate):
            self.offset = 1 - self.offset
        else:
            self.offset = int(random() < 0.5)

        for i in range(s+self.offset, len(self), 2):
            yield self[i] # yield selected items
        debugPrint(f"compacting {s}:\t secsToComp {secsToCompact}\t height {self.height}\t capacity {self.capacity()}\t size {len(self)}\t secSize {self.sectionSize}\t numSecs {self.numSections}")
        self[s:] = [] # delete items that are not selected
        debugPrint(f"compaction done: size {len(self)}")

        self.numCompaction += 1

    def capacity(self):
        cap = self.never + self.numSections * self.sectionSize + self.always
        assert(cap > 1)
        return cap

    def rank(self, value):
        return sum(1 for v in self if v <= value)

# AUXILIARY FUNCTIONS
def trailing_zeros(n):
    s = str(n)
    return len(s)-len(s.rstrip('0'))

def debugPrint(s):
    if debug:
        print(s)

debug = False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-eps', type=float, default=0.01,
                        help='controls the accuracy of the sketch which is, default is 0.01; alternatively, accuracy can be controlled by -sec, -never, and -always')
    parser.add_argument('-t', type=str, choices=["string", "int", "float"], default='int',
                        help='defines the type of stream items, default="int".')
    #parser.add_argument('-err', type=str, choices=["additive", "relative"], default='additive', # PV: SUPERSEDED BY THE FOLLOWING ARGUMENTS -- use -never=0, sectionSize=0, and always=k, for some k, for the additive error
    #                    help='sets the compactor to be either additive or relative, default="additive".')
    parser.add_argument('-sch', type=str, choices=["deterministic", "randomized"], default='deterministic',
                        help='sets the schedule of compactions on each level to either deterministic or randomized; default="deterministic".')
    parser.add_argument('-sec', type=int, default=-1,
                        help='size of each buffer section, should be even; by default set according to -eps.')
    parser.add_argument('-never', type=int, default=-1,
                        help='size of the buffer part that is never compacted, by default set to the section size times the number of sections.')
    parser.add_argument('-always', type=int, default=-1,
                        help='size of the buffer part that is always compacted, by default set to the section size.')
    parser.add_argument('-debug', type=bool, default=False,
                        help='print debug messages; default=False.')
    args = parser.parse_args()
    
    debug = args.debug
    eps = args.eps
    type = args.t
    conversions = {'int':int, 'string':str, 'float':float}
         
    sketch = RelativeErrorSketch(eps=eps, schedule=args.sch, always=args.always, never=args.never, sectionSize=args.sec)
    items = []
    for line in sys.stdin:
        item = conversions[type](line.strip('\n\r'))
        sketch.update(item)
        items.append(item)
     
    #cdf = sketch.cdf()
    #if args.cdf==True:
    #    for (item, quantile) in cdf:
    #        print(f"{quantile}\t{item}")
    
    # calculate maximum relative error
    ranks = sketch.ranks()
    items.sort()
    n = len(items)
    maxErrStored = 0
    print("item|apx.r.|true r.|err")
    # maximum relative error just among stored items
    for i in range(0, len(ranks)):
        (item, rank) = ranks[i]
        trueRank = items.index(item) + 1
        err = abs(trueRank - rank) / trueRank
        maxErrStored = max(maxErrStored, err)
        print(f"{item}\t{rank}\t{trueRank}\t{err}")

    # maximum relative error just among all items
    print("\n ************************************")
    maxErr = 0
    i = 1
    j = 0
    for item in items:
        if j < len(ranks) - 1 and item == ranks[j+1][0]:
            j += 1
        (stored, rank) = ranks[j]
        err = abs(rank - i) / i
        maxErr = max(maxErr, err)
        #print(f"item {item}\t stored {stored}\t rank {rank}\t trueRank {i}\t{err}")
        i += 1


    print(f"n={n}\nmax rel. error {maxErr}\nmax rel. error of stored {maxErrStored}\nfinal size {sketch.size}\nmaxSize {sketch.maxSize}")
