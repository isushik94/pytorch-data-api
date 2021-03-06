
class _TensorsIterator:
    def __init__(self, session_id, tensors):
        self._session_id = session_id
        self._tensors = tensors

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._tensors is None:
            raise StopAsyncIteration()
        else:
            try:
                return self._tensors
            finally:
                self._tensors = None


class TensorsDataSource:
    def __init__(self, *, tensors):
        self._tensors = tensors

    def get_iter(self, session_id):
        return _TensorsIterator(session_id, self._tensors)
