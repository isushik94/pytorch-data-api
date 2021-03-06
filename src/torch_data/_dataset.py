import asyncio
import aioitertools
import os


class _EmptyDatasetIterator:
    def __init__(self, session_id):
        self._session_id = session_id

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration()


class _EmptyDatasetSource:
    def get_iter(self, session_id):
        return _EmptyDatasetIterator(session_id)


class _DatasetAsyncIterator:
    def __init__(self, session_id, source):
        self._session_id = session_id
        self._source_iter = source.get_iter(session_id)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await aioitertools.next(self._source_iter)


class _DatasetSyncIterator:
    def __init__(self, async_iter):
        from signal import SIGINT, SIGTERM

        self._async_iter = aioitertools.iter(async_iter)

        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply(loop)

            old_loop = loop
            loop = asyncio.new_event_loop()
        else:
            old_loop = None

        def raise_keyboard():
            raise KeyboardInterrupt()

        def raise_exit():
            raise SystemExit()

        loop.add_signal_handler(SIGINT, raise_keyboard)
        loop.add_signal_handler(SIGTERM, raise_exit)

        self._old_loop = old_loop
        self._loop = loop

    async def __next(self):
        return await aioitertools.next(self._async_iter)

    def __del__(self):
        if self._old_loop is not None:
            self._loop.close()

    def __iter__(self):
        return self

    def __next__(self):
        try:
            task = self.__next()
            if self._old_loop is None:
                result = self._loop.run_until_complete(task)
            else:
                try:
                    asyncio.set_event_loop(self._loop)
                    result = self._loop.run_until_complete(task)
                finally:
                    asyncio.set_event_loop(self._old_loop)

            return result
        except StopAsyncIteration:
            raise StopIteration()


class Dataset:
    @staticmethod
    def from_generator(generator, args=None):
        from ._sources import GeneratorDataSource

        assert callable(generator), 'generator: Must be callable'
        assert args is None or isinstance(args, (list, tuple)), 'args: Must be None or a tuple'

        source = GeneratorDataSource(generator=generator, args=args)
        return Dataset(_source=source)

    @staticmethod
    def from_tensor_slices(*tensor_args, tensors=None):
        from ._sources import TensorSlicesDataSource

        from collections.abc import Iterable

        assert bool(len(tensor_args)) != (tensors is not None), \
            'tensors: only one way of initialization is supported'

        if len(tensor_args):
            tensors = tensor_args
        else:
            if not isinstance(tensors, tuple):
                tensors = (tensors,)

        if len(tensors) == 1 and isinstance(tensors[0], Dataset):
            return Dataset(_source=tensors[0].__source)
        else:
            state = all([isinstance(t, Iterable) for t in tensors])
            assert state, 'tensors: all tensors in the tuple must be iterable'

            state = all([not isinstance(t, Dataset) for t in tensors])
            assert state, 'tensors: `Dataset` items is not supported yet'

            source = TensorSlicesDataSource(tensors=tensors)
            return Dataset(_source=source)

    @staticmethod
    def from_tensors(*tensor_args, tensors=None):
        from ._sources import TensorsDataSource

        assert bool(len(tensor_args)) != (tensors is not None), \
            'tensors: only one way of initialization is supported'

        if len(tensor_args):
            tensors = tensor_args
        else:
            if not isinstance(tensors, tuple):
                tensors = (tensors,)

        states = set([len(t) for t in tensors])
        assert len(states) == 1, 'tensors: all tensors in the tuple must have the same length'

        source = TensorsDataSource(tensors=tensors)
        return Dataset(_source=source)

    @staticmethod
    def concatenate(*dataset_args, datasets=None, auto_prefetch=False):
        from ._sources import ConcatenateDataSource
        from ._ops import PrefetchDataOperation

        if datasets is None:
            datasets = dataset_args

        assert isinstance(datasets, (list, tuple)) and len(datasets), \
            'datasets: must be a non-empty instance of a list or tuple'
        assert all([isinstance(d, Dataset) for d in datasets]), \
            'datasets: all arguments must be an instance of Dataset class'

        if len(datasets) == 1:
            return datasets[0]
        else:
            if auto_prefetch:
                def map_fn(ds):
                    source = ds.__source
                    if not isinstance(source, PrefetchDataOperation):
                        source = PrefetchDataOperation(source=source, buffer_size=1)
                    return Dataset(_source=source)

                datasets = map(map_fn, datasets)

            dataset_sources = [dataset.__source for dataset in datasets]
            source = ConcatenateDataSource(dataset_sources=dataset_sources)
            return Dataset(_source=source)

    @staticmethod
    def interleave(*dataset_args, datasets=None, drop_tails=False, auto_prefetch=False):
        from ._sources import InterleaveDataSource
        from ._ops import PrefetchDataOperation

        if datasets is None:
            datasets = dataset_args

        assert isinstance(datasets, (list, tuple)) and len(datasets), \
            'datasets: must be a non-empty instance of a list or tuple'
        assert all([isinstance(d, Dataset) for d in datasets]), \
            'datasets: all arguments must be an instance of Dataset class'
        assert isinstance(drop_tails, bool), 'drop_tails: must be a boolean'

        if len(datasets) == 1:
            return datasets[0]
        else:
            if auto_prefetch:
                def map_fn(ds):
                    source = ds.__source
                    if not isinstance(source, PrefetchDataOperation):
                        source = PrefetchDataOperation(source=source, buffer_size=1)
                    return Dataset(_source=source)

                datasets = map(map_fn, datasets)

            dataset_sources = [dataset.__source for dataset in datasets]
            source = InterleaveDataSource(dataset_sources=dataset_sources, drop_tails=drop_tails)
            return Dataset(_source=source)

    #
    # operations

    def batch(self, batch_size, *, drop_last=True):
        from ._ops import BatchDataOperation

        assert isinstance(batch_size, int), 'batch_size: must be an integer'
        assert isinstance(drop_last, bool), 'drop_last: must be a boolean'

        op = BatchDataOperation(source=self.__source, batch_size=batch_size, drop_last=drop_last)
        return Dataset(_source=op)

    def batch_padded(self, batch_size, *, padded_shapes=None, padding_values=None, drop_last=True):
        from ._ops import BatchPaddedDataOperation

        assert isinstance(batch_size, int), 'batch_size: must be an integer'
        assert isinstance(drop_last, bool), 'drop_last: must be a boolean'

        op = BatchPaddedDataOperation(source=self.__source, batch_size=batch_size,
                                      padded_shapes=padded_shapes,
                                      padding_values=padding_values, drop_last=drop_last)
        return Dataset(_source=op)

    def collate(self, collate_func, buffer_size=None):
        from ._ops import CollateDataOperation

        assert callable(collate_func), 'collate_func: Must be callable'
        assert buffer_size is None or isinstance(buffer_size, int), 'buffer_size: must be an integer'
        assert buffer_size is None or buffer_size > 2, 'buffer_size: must be greater than 2'

        op = CollateDataOperation(source=self.__source, collate_func=collate_func, buffer_size=buffer_size)
        return Dataset(_source=op)

    def filter(self, predicate, expand_args=False):
        from ._ops import FilterDataOperation

        assert callable(predicate), 'predicate: Must be callable'

        op = FilterDataOperation(source=self.__source, predicate=predicate, expand_args=expand_args)

        return Dataset(_source=op)

    def map(self, map_func, num_parallel_calls=None, ordered=False, ignore_errors=False):
        from ._ops import MapDataOperation

        assert callable(map_func), 'map_func: Must be callable'
        assert num_parallel_calls is None or isinstance(num_parallel_calls, int), \
            'num_parallel_calls: Must be None or integer'

        if num_parallel_calls is None:
            num_parallel_calls = 0
        elif num_parallel_calls < 0:
            num_parallel_calls = os.cpu_count()

        op = MapDataOperation(source=self.__source, map_func=map_func,
                              num_parallel_calls=num_parallel_calls,
                              ordered=ordered, ignore_errors=ignore_errors)

        return Dataset(_source=op)

    def shuffle(self, buffer_size, seed=None):
        from ._ops import ShuffleDataOperation

        assert isinstance(buffer_size, int), 'buffer_size: must be an integer'
        assert buffer_size > 1, 'buffer_size: must be greater than 1'

        op = ShuffleDataOperation(source=self.__source, buffer_size=buffer_size, seed=seed)
        return Dataset(_source=op)

    def unbatch(self):
        from ._ops import UnBatchDataOperation

        op = UnBatchDataOperation(source=self.__source)
        return Dataset(_source=op)

    def window(self, size, stride=1, *, drop_last=True):
        from ._ops import WindowDataOperation

        assert isinstance(size, int), 'size: must be an integer'
        assert isinstance(stride, int), 'stride: must be an integer'
        assert isinstance(drop_last, bool), 'drop_last: must be a boolean'

        op = WindowDataOperation(source=self.__source, size=size, stride=stride, drop_last=drop_last)
        return Dataset(_source=op)

    def window_padded(self, size, stride=1, *, padded_shapes=None, padding_values=None, drop_last=True):
        from ._ops import WindowPaddedDataOperation

        assert isinstance(size, int), 'size: must be an integer'
        assert isinstance(stride, int), 'stride: must be an integer'
        assert isinstance(drop_last, bool), 'drop_last: must be a boolean'

        op = WindowPaddedDataOperation(source=self.__source, size=size, stride=stride,
                                       padded_shapes=padded_shapes,
                                       padding_values=padding_values, drop_last=drop_last)
        return Dataset(_source=op)

    def prefetch(self, size):
        from ._ops import PrefetchDataOperation

        assert isinstance(size, int), 'size: must be an integer'

        op = PrefetchDataOperation(source=self.__source, buffer_size=size)
        return Dataset(_source=op)

    # def repeat(self, times=None):
    #     pass

    #
    #
    #

    def __init__(self, *, _source=None):
        self.__source = _source
        if _source is None:
            self.__source = _EmptyDatasetSource()
        else:
            self.__source = _source

    def __aiter__(self):
        import uuid
        from ._ops import PrefetchDataOperation

        session_id = uuid.uuid4().hex

        source = self.__source
        if not isinstance(source, PrefetchDataOperation):
            source = PrefetchDataOperation(source=source, buffer_size=1)

        return _DatasetAsyncIterator(session_id, source)

    def __iter__(self):
        return _DatasetSyncIterator(self.__aiter__())
