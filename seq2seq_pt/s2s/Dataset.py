from __future__ import division

import math
import random

import torch
from torch.autograd import Variable

import s2s


class Dataset(object):
    def __init__(self, srcData, eqMaskData, ldaData, tgtData, batchSize, cuda):
        self.src = srcData
        self.eqMask = eqMaskData
        self.lda = ldaData
        if tgtData:
            self.tgt = tgtData
            assert (len(self.src) == len(self.tgt))
        else:
            self.tgt = None
        self.device = torch.device("cuda" if cuda else "cpu")

        self.batchSize = batchSize
        self.numBatches = math.ceil(len(self.src) / batchSize)

    def _batchify(self, data, align_right=False, include_lengths=False):
        lengths = [x.size(0) for x in data]
        max_length = max(lengths)
        out = data[0].new(len(data), max_length).fill_(s2s.Constants.PAD)
        for i in range(len(data)):
            data_length = data[i].size(0)
            offset = max_length - data_length if align_right else 0
            out[i].narrow(0, offset, data_length).copy_(data[i])

        if include_lengths:
            return out, lengths
        else:
            return out

    def __getitem__(self, index):
        assert index < self.numBatches, "%d > %d" % (index, self.numBatches)
        srcBatch, lengths = self._batchify(
            self.src[index * self.batchSize:(index + 1) * self.batchSize],
            align_right=False, include_lengths=True)
        ldaBatch, lda_length = self._batchify(self.lda[index * self.batchSize:(index + 1) * self.batchSize],
                                              include_lengths=True)
        lda_length = torch.LongTensor(lda_length)
        eqMaskBatch = self._batchify(self.eqMask[index * self.batchSize:(index + 1) * self.batchSize])

        if self.tgt:
            tgtBatch = self._batchify(
                self.tgt[index * self.batchSize:(index + 1) * self.batchSize])
        else:
            tgtBatch = None

        # within batch sorting by decreasing length for variable length rnns
        indices = range(len(srcBatch))
        if tgtBatch is None:
            batch = zip(indices, srcBatch, eqMaskBatch, ldaBatch, lda_length)
        else:
            batch = zip(indices, srcBatch, eqMaskBatch, ldaBatch, lda_length, tgtBatch)
        # batch = zip(indices, srcBatch) if tgtBatch is None else zip(indices, srcBatch, tgtBatch)
        batch, lengths = zip(*sorted(zip(batch, lengths), key=lambda x: -x[1]))
        if tgtBatch is None:
            indices, srcBatch, eqMaskBatch, ldaBatch, lda_length = zip(*batch)
        else:
            indices, srcBatch, eqMaskBatch, ldaBatch, lda_length, tgtBatch = zip(*batch)

        def wrap(b, batch_first=False):
            if b is None:
                return b
            if not batch_first:
                b = torch.stack(b, 0).t().contiguous()
            else:
                b = torch.stack(b, 0).contiguous()
            b = b.to(self.device)
            return b

        # wrap lengths in a Variable to properly split it in DataParallel
        lengths = torch.LongTensor(lengths).view(1, -1)

        return (wrap(srcBatch), lengths), (wrap(ldaBatch), lda_length), (wrap(tgtBatch),), (wrap(eqMaskBatch),), indices

    def __len__(self):
        return self.numBatches

    def shuffle(self):
        data = list(zip(self.src, self.eqMask, self.lda, self.tgt))
        self.src, self.eqMask, self.lda, self.tgt = zip(*[data[i] for i in torch.randperm(len(data))])
