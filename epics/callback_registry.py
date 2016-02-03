import sys
import logging
from . import ca
from . import dbr


logger = logging.getLogger(__name__)


# 'connection', chid
# 'monitor', chid, mask, ftype

class MonitorCallback:
    # a monitor can be reused if:
    #   amask = available_mask / atype = available_type
    #   rmask = requested_mask / rtype = requested_type
    #   (amask & rmask) == rmask
    #   (rtype <= atype)
    default_mask = (dbr.SubscriptionType.DBE_VALUE |
                    dbr.SubscriptionType.DBE_ALARM)

    def __init__(self, chid, *, mask=default_mask, ftype=None):
        '''
        mask : int
            channel mask from dbr.SubscriptionType
            default is (DBE_VALUE | DBE_ALARM)

        '''
        if mask <= 0:
            raise ValueError('Invalid subscription mask')

        if ftype is None:
            ftype = ca.field_type(chid)

        self.chid = ca.channel_id_to_int(chid)
        self.mask = int(mask)
        self.ftype = int(ftype)
        self._hash_tuple = (self.chid, self.mask, self.ftype)

    def __repr__(self):
        return ('{0.__class__.__name__}(chid={0.chid}, mask={0.mask:04b}, '
                'ftype={0.ftype})'.format(self))

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __hash__(self):
        return hash(self._hash_tuple)

    def __lt__(self, other):
        return not (self >= other)

    def __le__(self, other):
        return (self == other) or (self < other)

    def __ge__(self, other):
        if self.chid != other.chid:
            raise TypeError('Cannot compare subscriptions from different '
                            'channels')

        has_req_mask = (other.mask & self.mask) == other.mask
        type_ok = self.ftype >= other.ftype
        return has_req_mask and type_ok


class ChannelCallbackRegistry:
    def __init__(self, ignore_exceptions=False, allowed_sigs=None):
        self.ignore_exceptions = ignore_exceptions
        self.allowed_sigs = allowed_sigs
        self.callbacks = dict()
        self._cbid = 0
        self._cbid_map = {}
        self._oneshots = {}

    def __getstate__(self):
        # We cannot currently pickle the callables in the registry, so
        # return an empty dictionary.
        return {}

    def __setstate__(self, state):
        # re-initialise an empty callback registry
        self.__init__()

    def subscribe(self, sig, chid, func, *, oneshot=False):
        """Register ``func`` to be called when ``sig`` is generated
        Parameters
        ----------
        sig
        func
        Returns
        -------
        cbid : int
            The callback index. To be used with ``disconnect`` to deregister
            ``func`` so that it will no longer be called when ``sig`` is
            generated
        """
        if self.allowed_sigs is not None:
            if sig not in self.allowed_sigs:
                raise ValueError("Allowed signals are {0}".format(
                    self.allowed_sigs))

        self._cbid += 1
        cbid = self._cbid
        chid = ca.channel_id_to_int(chid)

        self.callbacks.setdefault(sig, dict())
        self.callbacks[sig].setdefault(chid, dict())

        self.callbacks[sig][chid][cbid] = func
        self._cbid_map[cbid] = (sig, chid)

        if oneshot:
            self._oneshots[cbid] = True
        return cbid

    def unsubscribe(self, cbid):
        """Disconnect the callback registered with callback id *cbid*
        Parameters
        ----------
        cbid : int
            The callback index and return value from ``connect``
        """
        sig, chid = self._cbid_map[cbid]
        del self._cbid_map[cbid]

        del self.callbacks[sig][chid][cbid]
        if not self.callbacks[sig][chid]:
            del self.callbacks[sig][chid]

        try:
            del self._oneshots[cbid]
        except KeyError:
            pass

    def process(self, sig, chid, **kwargs):
        """Process ``sig``
        All of the functions registered to receive callbacks on ``sig``
        will be called with ``args`` and ``kwargs``
        Parameters
        ----------
        sig
        args
        kwargs
        """
        if self.allowed_sigs is not None:
            if sig not in self.allowed_sigs:
                raise ValueError("Allowed signals are {0}"
                                 "".format(self.allowed_sigs))

        exceptions = []

        print('sig', sig, 'chid', chid)
        if sig not in self.callbacks:
            logger.error('? sig')
            return
        if chid not in self.callbacks[sig]:
            logger.error('? chid')
            return

        callbacks = self.callbacks[sig][chid]
        # TODO more efficient way
        for cbid, func in list(callbacks.items()):
            oneshot = self._oneshots.get(cbid, False)
            try:
                func(chid=chid, **kwargs)
            except Exception as ex:
                if not self.ignore_exceptions:
                    raise

                exceptions.append((ex, sys.exc_info()[2]))
                logger.error('Unhandled callback exception', exc_info=ex)
            finally:
                if oneshot:
                    self.unsubscribe(cbid)

        return exceptions
