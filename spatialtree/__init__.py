#!/usr/bin/env python
'''
CREATED:2011-11-11 13:53:46 by Brian McFee <bmcfee@cs.ucsd.edu>

Implementation of spatial trees:
    * Max-variance KD
    * PCA tree
    * 2-means tree
    * RP tree

Also supports spill trees.

See: docs for spatialtree.spatialtree
'''

import numpy
import scipy.stats
import random
import heapq

class spatialtree(object):

    def __init__(self, data, **kwargs):
        '''
        T = spatialtree(    data, 
                            rule='kd', 
                            spill=0.25, 
                            height=H, 
                            indices=(index1, index2,...), 
                            min_items=64,
                            steps_2means=1000,
                            samples_rp=10)
                            

        Required arguments:
            data:           d-by-n data matrix (numpy.ndarray), one point per column
                            alternatively, may be a dict of vectors

        Optional arguments:
            rule:           must be one of 'kd', 'pca', '2-means', 'rp'

            spill:          what fraction of the data should propagate to both children during splits
                            must lie in range [0,1)

                            Setting spill=0 yields a partition tree

            height>0:       maximum-height to build the tree
                            default is calculated to yield leaves with ~500 items each

            indices:        list of keys/indices to store in this (sub)tree
                            default: 0:n-1, or data.keys()

            min_items:      the minimum number of items required to split a node

        Split-specific:
            steps_2means:   minimum number of steps for building the 2-means tree

            samples_rp:     number of directions to consider for each RP split
        '''

        # Default values
        if 'indices' not in kwargs:
            if isinstance(data, dict):
                kwargs['indices']   = data.keys()
            else:
                kwargs['indices']   = range(len(data))
            pass
        
        n = len(kwargs['indices'])

        # Use maximum-variance kd by default
        if 'rule' not in kwargs:
            kwargs['rule']          = 'kd'
            pass

        kwargs['rule'] = kwargs['rule'].lower()


        # By default, 25% of items propagate to both subtrees
        if 'spill' not in kwargs:
            kwargs['spill']         = 0.25
            pass

        if kwargs['spill'] < 0.0 or kwargs['spill'] >= 1.0:
            raise ValueError('spill=%.2e, must lie in range [0,1)' % kwargs['spill'])

        if 'height' not in kwargs:
            # This calculates the height necessary to achieve leaves of roughly 500 items,
            # given the current spill threshold
            kwargs['height']    =   max(0, int(numpy.ceil(numpy.log(n / 500) / numpy.log(2.0 / (1 + kwargs['spill'])))))
            pass

        if 'min_items' not in kwargs:
            kwargs['min_items']     = 64
            pass

        if kwargs['rule'] == '2-means' and 'steps_2means' not in kwargs:
            kwargs['steps_2means']  = 1000
            pass 

        if kwargs['rule'] == 'rp' and 'samples_rp' not in kwargs:
            kwargs['samples_rp']    = 10
            pass


        # All information is now contained in kwargs, we may proceed
        
        # Store bookkeeping information
        self.__indices      = set(kwargs['indices'])
        self.__splitRule    = kwargs['rule']
        self.__spill        = kwargs['spill']
        self.__children     = None
        self.__w            = None
        self.__thresholds   = None
        self.__keyvalue     = isinstance(data, dict)



        # Compute the dimensionality of the data
        # This way supports opaque key-value stores as well as numpy arrays
        for x in self.__indices:
            self.__d = len(data[x])
            break

        # Split the new node
        self.__height       = self.__split(data, **kwargs)

        pass

    def __split(self, data, **kwargs):

        # First, find the split rule
        if kwargs['rule'] == 'pca':
            splitF  =   self.__PCA
        elif kwargs['rule'] == 'kd':
            splitF  =   self.__KD
        elif kwargs['rule'] == '2-means':
            splitF  =   self.__2means
        elif kwargs['rule'] == 'rp':
            splitF  =   self.__RP
        else:
            raise ValueError('Unsupported split rule: %s' % kwargs['rule'])

        # If the height is 0, we don't need to split
        if kwargs['height'] == 0:
            return  0

        if kwargs['height'] < 1:
            raise ValueError('spatialtree.split() called with height<0')

        if len(kwargs['indices']) < kwargs['min_items']:
            return  0

        # Compute the split direction 
        self.__w = splitF(data, **kwargs)

        # Project onto direction
        wx = {}
        for i in self.__indices:
            wx[i] = numpy.dot(self.__w, data[i])
            pass

        # Compute the bias points
        self.__thresholds = scipy.stats.mstats.mquantiles(wx.values(), [0.5 - self.__spill/2, 0.5 + self.__spill/2])

        # Partition the data
        left_set    = set()
        right_set   = set()

        for (i, val) in wx.iteritems():
            if val >= self.__thresholds[0]:
                right_set.add(i)
            if val < self.__thresholds[-1]:
                left_set.add(i)
            pass
        del wx

        # Construct the children
        self.__children     = [ None ] * 2
        kwargs['height']    -= 1

        kwargs['indices']   = left_set
        self.__children[0]  = spatialtree(data, **kwargs)
        del left_set

        kwargs['indices']   = right_set
        self.__children[1]  = spatialtree(data, **kwargs)
        del right_set

        # Done
        return 1 + max(self.__children[0].getHeight(), self.__children[1].getHeight())

    def update(self, D):
        '''
        T.update({new_key1: new_vector1, [new_key2: new_vector2, ...]})

        Add new data to the tree.  Note: this does not rebalance or split the tree.

        Only valid when using key-value stores.
        '''

        if not self.__keyvalue:
            raise TypeError('update method only supported when using key-value stores')

        self.__indices.update(D.keys())

        if self.__children is None:
            return

        left_set    = {}
        right_set   = {}
        for (key, vector) in D.iteritems():
            wx = numpy.dot(self.__w, vector)

            if wx >= self.__thresholds[0]:
                right_set[key]  = vector
            if wx < self.__thresholds[-1]:
                left_set[key]   = vector
            pass

        self.__children[0].update(left_set)
        del left_set
        self.__children[1].update(right_set)

        pass

    # Getters and container methods
    def getHeight(self):
        return self.__height

    def getRule(self):
        return self.__splitRule

    def getSpill(self):
        return self.__spill

    def getSplit(self):
        return (self.__w, self.__thresholds)

    def getDimension(self):
        return self.__d

    def __len__(self):
        return len(self.__indices)

    def __contains(self, x):
        return x in self.__indices

    def __iter__(self):
        return self.__indices.__iter__()

    # RETRIEVAL CODE

    def retrievalSet(self, **kwargs):
        '''
        S = T.retrievalSet(index=X, vector=X)
        
        Compute the retrieval set for either a given query index or vector.

        Exactly one of index or data must be supplied
        '''

        if 'index' in kwargs:
            return self.__retrieveIndex(kwargs['index'])
        elif 'vector' in kwargs:
            return self.__retrieveVector(kwargs['vector'])

        raise Exception('spatialtree.retrievalSet must be supplied with either an index or a data vector')
        pass


    def __retrieveIndex(self, index):

        S = set()
        
        if index in self.__indices:
            if self.__children is None:
                S = self.__indices.difference([index])
            else:
                S = self.__children[0].__retrieveIndex(index) | self.__children[1].__retrieveIndex(index)
            pass

        return S

    def __retrieveVector(self, vector):

        S = set()

        # Did we land at a leaf?  Must be done
        if self.__children is None:
            S = self.__indices
        else:
            Wx = numpy.dot(self.__w, vector)

            # Should we go right?
            if Wx >= self.__thresholds[0]:
                S |= self.__children[1].__retrieveVector(vector)
                pass

            # Should we go left?
            if Wx < self.__thresholds[-1]:
                S |= self.__children[0].__retrieveVector(vector)
                pass

        return S


    def k_nearest(self, data, **kwargs):
        '''
        neighbors = T.k_nearest(data, k=10, index=X, vector=X)

        data:       the data matrix/dictionary
        k:          the number of (approximate) nearest neighbors to return

        index=X:    the index of the query point OR
        vector=X:   a data vector to query against

        Returns:
        A sorted list of the indices of k-nearest (approximate) neighbors of the query
        '''


        if 'k' not in kwargs:
            raise Exception('k_nearest called with no value of k')

        if not isinstance(kwargs['k'], int):
            raise TypeError('k_nearest must be called with an integer value of k')
        if kwargs['k'] < 1:
            raise ValueError('k must be a positive integer')

        # Get the retrieval set
        if 'index' in kwargs:
            x = data[kwargs['index']]
        else:
            x = kwargs['vector']
            pass

        # Now compute distance from query point to the retrieval set
        def dg(S):
            for i in S:
                yield (numpy.sum((x-data[i])**2), i)
            pass

        S = heapq.nsmallest(kwargs['k'], dg(self.retrievalSet(**kwargs)))

        return [i for (d,i) in S]


    # SPLITTING RULES

    def __PCA(self, data, **kwargs):
        # first moment
        moment_1 = numpy.zeros(self.__d)

        # second moment
        moment_2 = numpy.zeros((self.__d, self.__d))

        # Compute covariance matrix
        for i in self.__indices:
            moment_1 += data[i]
            moment_2 += numpy.outer(data[i], data[i])
            pass

        # the mean
        moment_1    /= len(self)

        # the covariance
        sigma       = (moment_2 - (len(self) * numpy.outer(moment_1, moment_1))) / (len(self)- 1.0)

        # eigendecomposition
        (l, v)      = numpy.linalg.eigh(sigma)
        
        # top eigenvector
        w           = v[numpy.argmax(l)]
        return w

    def __KD(self, data, **kwargs):
        moment_1 = numpy.zeros(self.__d)
        moment_2 = numpy.zeros(self.__d)

        for i in self.__indices:
            moment_1 += data[i]
            moment_2 += data[i] ** 2
            pass

        # mean
        moment_1    /= len(self)

        # variance
        sigma       = (moment_2 - (len(self) * moment_1**2)) / (len(self) - 1.0)

        # the coordinate of maximum variance
        w           = numpy.zeros(self.__d)
        w[numpy.argmax(sigma)] = 1
        return w

    def __2means(self, data, **kwargs):
        def D(u,v):
            return numpy.sum( (u-v)**2 )

        centers     = numpy.zeros( (2, self.__d) )
        counters    = [0] * 2

        index       = list(self.__indices)
        count       = 0
        num_steps   = max(len(self), kwargs['steps_2means'])

        while True:
            # Randomly permute the index
            random.shuffle(index)
            
            for i in index:
                # Find the closest centroid
                j_min = numpy.argmin([D(data[i], mu) * c / (1.0 + c) for (mu, c) in zip(centers, counters)])

                centers[j_min,:] = (centers[j_min,:] * counters[j_min] + data[i]) / (counters[j_min]+1)
                counters[j_min] += 1

                count += 1
                if count > num_steps:
                    break
                pass
            if count > num_steps:
                break

        w = centers[0,:] - centers[1,:]

        w /= numpy.sqrt(numpy.sum(w**2))
        return w


    def __RP(self, data, **kwargs):
        k   = kwargs['samples_rp']

        # sample directions from d-dimensional normal
        W   = numpy.random.randn( k, self.__d )

        # normalize each sample to get a sample from unit sphere
        for i in xrange(k):
            W[i,:] /= numpy.sqrt(numpy.sum(W[i,:]**2))
            pass

        # Find the direction that maximally spreads the data:

        min_val = numpy.inf * numpy.ones(k)
        max_val = -numpy.inf * numpy.ones(k)

        for i in self.__indices:
            Wx      = numpy.dot(W, data[i])
            min_val = numpy.minimum(min_val, Wx)
            max_val = numpy.maximum(max_val, Wx)
            pass

        return W[numpy.argmax(max_val - min_val),:]

# end
