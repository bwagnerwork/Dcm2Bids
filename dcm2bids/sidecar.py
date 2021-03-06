# -*- coding: utf-8 -*-


import itertools
import logging
import os
import re
from collections import defaultdict, OrderedDict
from fnmatch import fnmatch
from fnmatch import filter as fnfilter
from future.utils import iteritems
from .structure import Acquisition
from .utils import DEFAULT, load_json, save_json, splitext_, is_numeric

import nibabel
import math

class Sidecar(object):
    """ A sidecar object

    Args:
        filename (str): Path of a JSON sidecar
        keyComp (list): A list of keys from the JSON sidecar to compare sidecars
                     default=["SeriesNumber","AcquisitionTime","SideCarFilename"]
    """

    def __init__(self, filename, compKeys=DEFAULT.compKeys):
        self._origData = {}
        self._data = {}

        self.filename = filename
        self.root, _ = splitext_(filename)
        self.data = filename
        self.compKeys = compKeys


    def __lt__(self, other):
        lts = []
        for key in self.compKeys:
            try:
                lts.append(self.data.get(key) < other.data.get(key))
            except:
                lts.append(False)

        for lt in lts:
            if lt:
                return True
            else:
                pass

        return False


    def __eq__(self, other):
        return self.data == other.data


    def __hash__(self):
        return hash(self.filename)


    @property
    def origData(self):
        return self._origData


    @property
    def data(self):
        return self._data


    @data.setter
    def data(self, filename):
        """
        Args:
            filename (path): path of a JSON file

        Return:
            A dictionnary of the JSON content plus the SidecarFilename
        """
        try:
            data = load_json(filename)
        except:
            data = {}

        nii = None
        if os.path.isfile(filename.replace('.json','.nii.gz')):
            nii = filename.replace('.json','.nii.gz')
        elif os.path.isfile(filename.replace('.json','.nii')):
            nii = filename.replace('.json','.nii')

        if nii:
            img = nibabel.load(nii)
            for k in img.header.keys():
                tmp_v = img.header.get(k).tolist()
                if isinstance(tmp_v, list) and len(tmp_v) == 1:
                    tmp_v = tmp_v[0]
                data['nii_' + k] = tmp_v
                    
                if isinstance(data['nii_' + k], bytes):
                    data['nii_' + k] = data['nii_' + k].decode('ASCII')
                if is_numeric(data['nii_' + k]) and math.isnan(data['nii_' + k]):
                    data['_nii_' + k] = 'Value initially {}, but set to 0 '\
                                        '(not null) for BIDS-validator '\
                                        'compliance'.format(data['nii_' + k])
                    data['nii_' + k] = 0

        self._origData = data.copy()
        data["SidecarFilename"] = os.path.basename(filename)
        self._data = data


class SidecarPairing(object):
    """
    Args:
        sidecars (list): List of Sidecar objects
        descriptions (list): List of dictionnaries describing acquisitions
    """

    def __init__(self, sidecars, descriptions,
            searchMethod=DEFAULT.searchMethod):
        self.logger = logging.getLogger(__name__)

        self._searchMethod = ""
        self.graph = OrderedDict()
        self.aquisitions = []

        self.sidecars = sidecars
        self.descriptions = descriptions
        self.searchMethod = searchMethod


    @property
    def searchMethod(self):
        return self._searchMethod


    @searchMethod.setter
    def searchMethod(self, value):
        """
        Checks if the search method is implemented
        Warns the user if not and fall back to default
        """
        if value in DEFAULT.searchMethodChoices:
            self._searchMethod = value

        else:
            self._searchMethod = DEFAULT.searchMethod
            self.logger.warning(
                    "'{}' is not a search method implemented".format(value))
            self.logger.warning(
                    "Falling back to default: {}".format(DEFAULT.searchMethod))
            self.logger.warning("Search methods implemented: {}".format(
                    DEFAULT.searchMethodChoices))


    def build_graph(self):
        """
        Test all the possible links between the list of sidecars and the
        description dictionnaries and build a graph from it
        The graph is in a OrderedDict object. The keys are the Sidecars and
        the values are a list of possible descriptions

        Returns:
            A graph (OrderedDict)
        """
        graph = OrderedDict((_, []) for _ in self.sidecars)

        possibleLinks = itertools.product(self.sidecars, self.descriptions)
        for sidecar, description in possibleLinks:
            criteria = description.get("criteria", None)
            if criteria and self.isLink(sidecar.data, criteria):
                graph[sidecar].append(description)
                description['__num_runs'] = description.get('__num_runs', 0) + 1

        self.graph = graph
        return graph


    def isLink(self, data, criteria):
        """
        Args:
            data (dict): Dictionnary data of a sidecar
            criteria (dict): Dictionnary criteria

        Returns:
            boolean
        """
        def compare(name, pattern):
            if is_numeric(name) and is_numeric(pattern):
                return name == pattern
            elif is_numeric(name) \
                 and isinstance(pattern, list) \
                 and len(pattern) == 2 \
                 and is_numeric(pattern[0]) \
                 and is_numeric(pattern[1]):
                return (name >= pattern[0] and name <= pattern[1])
            elif self.searchMethod == "re":
                return bool(re.search(pattern, str(name)))
            else:
                return fnmatch(str(name), str(pattern))

        def compare_list(name, pattern):
            try:
                subResult = [
                        len(name)==len(pattern),
                        isinstance(pattern, list),
                        ]
                for subName, subPattern in zip(name, pattern):
                    subResult.append(compare(subName, subPattern))
            except:
                subResult = [False]
            return all(subResult)

        def compare_complex(name, pattern):
            sub_result = []
            compare_type = None
            try:
                for compare_type, patterns in pattern.items():
                    for sub_pattern in patterns:
                        if isinstance(name, list):
                            sub_result.append(compare_list(name,sub_pattern))
                        else:
                            sub_result.append(compare(name, sub_pattern))
            except:
                sub_result = [False]
            if compare_type == "any":
                return any(sub_result)
            elif compare_type == "all":
                return all(sub_result)
            else:
                return False

        result = []
        tags = []
        for tag, pattern in iteritems(criteria):
            tags.append(tag)
            name = data.get(tag)
            if isinstance(pattern, dict):
                result.append(compare_complex(name, pattern))
            elif isinstance(name, list):
                result.append(compare_list(name, pattern))
            else:
                result.append(compare(name, pattern))
        if True and 'ProtocolName' in criteria and result[list(criteria).index('ProtocolName')]:
            print('-'*80)
            print(data.get('SidecarFilename'))
            # print(criteria)
            for t,r in list(zip(tags,result)):
                if r:
                    print('Match  {}: {}'.format(t, criteria.get(t)))
                else:
                    print('Failed {}: {}'.format(t, criteria.get(t)))
                    print('   got {}: {}'.format(t, data.get(t)))
        return all(result)


    def build_acquisitions(self, participant):
        """
        Args:
            participant (Participant): Participant object to create acquisitions
        Returns:
            A list of acquisition objects
        """
        acquisitions = []

        self.logger.info("Sidecars pairing:")
        for sidecar, descriptions in iteritems(self.graph):
            sidecarName = os.path.basename(sidecar.root)

            #only one description for the sidecar
            if len(descriptions) == 1:
                desc = descriptions[0]
                acq = Acquisition(participant, srcSidecar=sidecar, **desc)
                acquisitions.append(acq)

                self.logger.info("{}  <-  {}".format(
                    acq.suffix, sidecarName))

            #sidecar with no link
            elif len(descriptions) == 0:
                self.logger.info("No Pairing  <-  {}".format(sidecarName))

            #sidecar with several links
            else:
                self.logger.warning(
                        "Several Pairing  <-  {}".format(sidecarName))
                for desc in descriptions:
                    acq = Acquisition(participant, **desc)
                    self.logger.warning("    ->  " + acq.suffix)

        self.acquisitions = acquisitions
        return acquisitions


    def find_runs(self):
        """
        Check if there is duplicate destination roots in the acquisitions
        and add '_run-' to the customLabels of the acquisition
        """
        def duplicates(seq):
            """ Find duplicate items in a list

            Args:
                seq (list)

            Yield:
                A tuple of 2 items (item, list of index)

            ref: http://stackoverflow.com/a/5419576
            """
            tally = defaultdict(list)
            for i, item in enumerate(seq):
                tally[item].append(i)

            for key, locs in iteritems(tally):
                if len(locs) > 1:
                    yield key, locs

        dstRoots = [_.dstRoot for _ in self.acquisitions]
        for dstRoot, dup in duplicates(dstRoots):
            self.logger.info("{} has {} runs".format(dstRoot, len(dup)))
            self.logger.info("Adding 'run' information to the acquisition")

            for runNum, acqInd in enumerate(dup):
                runStr = DEFAULT.runTpl.format(runNum+1)
                self.acquisitions[acqInd].customLabels += runStr

    def fix_intended_for(self, bids_dir):
        tmp, base = os.path.split(bids_dir)
        if base[0:4] == "ses-":
            bids_dir = tmp
        self.logger.info("Fix Intended For:" + bids_dir)
        for root, dirs, files in os.walk(bids_dir):
            for fn in fnfilter(files, '*.json'):
                json_fn = os.path.join(root,fn)
                data = load_json(json_fn)
                intended_for = data.get('IntendedFor')
                if intended_for:
                    if not isinstance(intended_for,list):
                        intended_for = [intended_for]
                    data['_IntendedFor'] = intended_for[:]
                    for intended_file in intended_for:
                        if os.path.exists(os.path.join(bids_dir,intended_file)):
                            continue
                        self.logger.info('remove missing IntendedFor: ' + intended_file)
                        intended_for.remove(intended_file)
                    data['IntendedFor'] = intended_for
                    if data['_IntendedFor'] != data['IntendedFor']:
                        self.logger.info('write updated json: ' + json_fn)
                        save_json(json_fn, data)
