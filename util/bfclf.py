# -*- coding: latin-1 -*-
# -----------------------------------------------------------------------------
# Copyright 2009, 2017 Stephen Tiedemann <stephen.tiedemann@gmail.com>
#
# Licensed under the EUPL, Version 1.1 or - as soon they
# will be approved by the European Commission - subsequent
# versions of the EUPL (the "Licence");
# You may not use this work except in compliance with the
# Licence.
# You may obtain a copy of the Licence at:
#
# https://joinup.ec.europa.eu/software/page/eupl
#
# Unless required by applicable law or agreed to in
# writing, software distributed under the Licence is
# distributed on an "AS IS" basis,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied.
# See the Licence for the specific language governing
# permissions and limitations under the Licence.
# -----------------------------------------------------------------------------
# This file is a direct modification of https://github.com/nfcpy/nfcpy/blob/master/src/nfc/clf/__init__.py and thus inherits its license
# Modifications are targeted towards adding "Broadcast" frames functionality
# Parts of the code that were changed are denoted by "Modified code BEGIN" and "Modified code END" comments


import errno
import logging
import os
import time

import nfc.clf.pn53x
from nfc.clf import (
    CommunicationError,
    ContactlessFrontend,
    ProtocolError,
    RemoteTarget,
    UnsupportedTargetError,
)
from nfc.tag import activate

from util.nfc import with_crc16a

log = logging.getLogger(__name__)


class BroadcastFrameContactlessFrontend(ContactlessFrontend):
    # Modified code BEGIN
    def __init__(self, path=None, *, broadcast_enabled=False):
        self.broadcast_enabled = broadcast_enabled
        super().__init__(path)

    # Modified code END

    def sense(self, *targets, **options):
        def sense_tta(target):
            if target.sel_req and len(target.sel_req) not in (4, 7, 10):
                raise ValueError("sel_req must be 4, 7, or 10 byte")
            target = self.device.sense_tta(target)
            # log.debug("found %s", target)
            if target and len(target.sens_res) != 2:
                error = "SENS Response Format Error (wrong length)"
                log.debug(error)
                raise ProtocolError(error)
            if target and target.sens_res[0] & 0b00011111 == 0:
                if target.sens_res[1] & 0b00001111 != 0b1100:
                    error = "SENS Response Data Error (T1T config)"
                    log.debug(error)
                    raise ProtocolError(error)
                if not target.rid_res:
                    error = "RID Response Error (no response received)"
                    log.debug(error)
                    raise ProtocolError(error)
                if len(target.rid_res) != 6:
                    error = "RID Response Format Error (wrong length)"
                    log.debug(error)
                    raise ProtocolError(error)
                if target.rid_res[0] >> 4 != 0b0001:
                    error = "RID Response Data Error (invalid HR0)"
                    log.debug(error)
                    raise ProtocolError(error)
            return target

        def sense_ttb(target):
            return self.device.sense_ttb(target)

        def sense_ttf(target):
            return self.device.sense_ttf(target)

        def sense_dep(target):
            if len(target.atr_req) < 16:
                raise ValueError("minimum atr_req length is 16 byte")
            if len(target.atr_req) > 64:
                raise ValueError("maximum atr_req length is 64 byte")
            return self.device.sense_dep(target)

        # Modified code BEGIN
        def sense_broadcast(target, broadcast):
            # Correct implementation would be to define and call sense_broadcast from device implementation
            # and adding all support checks there. For simplicity, everthing has been included in one file here
            if not self.broadcast_enabled:
                return

            if broadcast is None or len(broadcast) <= 0:
                # Skip broadcast if nothing to broadcast
                return

            if not any(target.brty.endswith(m) for m in ("A", "B")):
                # Skip broadcast for any NFC type that's not A or B
                return

            if not isinstance(self.device.chipset, nfc.clf.pn53x.Chipset):
                raise UnsupportedTargetError(
                    f"Broadcast frames are not supported with chipset {self.device} for target {target}"
                )

            # Turn off detection retries at it might break broadcast frame sequence
            self.device.chipset.rf_configuration(0x05, [0xFF, 0x01, 0x00])

            if target.brty.endswith("A"):
                self.device.chipset.write_register("CIU_BitFraming", 0x00)
                broadcast = with_crc16a(broadcast)
            try:
                _ = self.device.chipset.in_communicate_thru(broadcast, timeout=0.1)
                # Can proccess response here later
            except (nfc.clf.pn53x.Chipset.Error,) as e:
                # Timeout is OK for broadcast frames as we don't always expect an answer
                if e.errno != 0x01:
                    raise

        # Modified code END

        for target in targets:
            if not isinstance(target, RemoteTarget):
                raise ValueError("invalid target argument type: %r" % target)

        with self.lock:
            if self.device is None:
                raise IOError(errno.ENODEV, os.strerror(errno.ENODEV))

            self.target = None  # forget captured target
            self.device.mute()  # deactivate the rf field

            for i in range(max(1, options.get("iterations", 1))):
                started = time.time()
                for target in targets:
                    # log.debug("sense {0}".format(target))
                    try:
                        if target.atr_req is not None:
                            self.target = sense_dep(target)
                        elif target.brty.endswith("A"):
                            self.target = sense_tta(target)
                        elif target.brty.endswith("B"):
                            self.target = sense_ttb(target)
                        elif target.brty.endswith("F"):
                            self.target = sense_ttf(target)
                        else:
                            info = "unknown technology type in %r"
                            raise UnsupportedTargetError(info % target.brty)
                        # Modified code BEGIN
                        if self.target is None:
                            sense_broadcast(target, options.get("broadcast", None))
                        # Modified code END
                    except UnsupportedTargetError as error:
                        if len(targets) == 1:
                            raise error
                        else:
                            log.debug(error)
                    except CommunicationError as error:
                        log.debug(error)
                    else:
                        if self.target is not None:
                            log.debug("found {0}".format(self.target))
                            return self.target
                if len(targets) > 0:
                    self.device.mute()  # deactivate the rf field
                if i < options.get("iterations", 1) - 1:
                    elapsed = time.time() - started
                    time.sleep(max(0, options.get("interval", 0.1) - elapsed))


__all__ = ("BroadcastFrameContactlessFrontend", "RemoteTarget", "activate")
