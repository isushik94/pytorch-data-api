
from ._sources import GeneratorDataSource, TensorSlicesDataSource, TensorsDataSource

from ._ops import BatchDataOperation, MapDataOperation, ShuffleDataOperation


class DatasetIterator:
    _none = object()

    def __init__(self, dataset):
        self._dataset = dataset
        self._dataset_iter = iter(self._dataset)

    def __iter__(self):
        return self

    def __next__(self):
        item = next(self._dataset_iter, self._none)
        if item is self._none:
            raise StopIteration()
        else:
            return item


class Dataset:
    @staticmethod
    def from_generator(generator, args=None):
        assert callable(generator), 'generator: Must be callable'
        assert args is None or isinstance(args, (list, tuple)), 'args: Must be None or a tuple'

        source = GeneratorDataSource(generator=generator, args=args)
        return Dataset(_impl=source)

    @staticmethod
    def from_tensor_slices(*tensor_args, tensors=None):
        source = TensorSlicesDataSource(*tensor_args, tensors=tensors)
        return Dataset(_impl=source)

    @staticmethod
    def from_tensors(*tensor_args, tensors=None):
        source = TensorsDataSource(*tensor_args, tensors=tensors)
        return Dataset(_impl=source)

    def __init__(self, *, _impl=None):
        assert _impl is not None, ''

        self.__impl = _impl

    @property
    def _impl(self):
        return self.__impl

    def __iter__(self):
        return DatasetIterator(self._impl)

    def concatenate(self, dataset):
        pass

    def interleave(self, dataset):
        pass

    def filter(self, predicate):
        pass

    def map(self, map_func, num_parallel_calls=None, ordered=True):
        assert callable(map_func), 'map_func: Must be callable'
        assert num_parallel_calls is None or isinstance(num_parallel_calls, int), \
            'num_parallel_calls: Must be None or integer'

        op = MapDataOperation(source=self._impl, map_func=map_func,
                              num_parallel_calls=num_parallel_calls,
                              ordered=ordered)

        return Dataset(_impl=op)

    def shuffle(self, buffer_size, seed=None):
        assert isinstance(buffer_size, int), 'buffer_size: must be an integer'
        assert buffer_size > 1, 'buffer_size: must be greater than 1'

        op = ShuffleDataOperation(source=self._impl, buffer_size=buffer_size, seed=seed)
        return Dataset(_impl=op)

    def batch(self, batch_size, *, drop_last=True):
        assert isinstance(batch_size, int), 'batch_size: must be an integer'
        assert isinstance(drop_last, int), 'drop_last: must be a boolean'

        op = BatchDataOperation(source=self._impl, batch_size=batch_size, drop_last=drop_last)
        return Dataset(_impl=op)

    def unbatch(self):
        pass

    def window(self, size, shift=None, stride=1, drop_remainder=False):
        pass
