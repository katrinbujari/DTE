
from luiginlp.engine import Task, StandardWorkflowComponent, WorkflowComponent, InputFormat, InputComponent, registercomponent, InputSlot, Parameter, IntParameter, BoolParameter

import json
import glob
import os
import datetime 
from collections import defaultdict

from dte.functions import event_merger
from dte.classes import event
from dte.modules.enhance_events import EnhanceEvents

################################################################################
###Event integrator
################################################################################

@registercomponent
class IntegrateEvents(StandardWorkflowComponent):

    current_events = Parameter()
    overlap_threshold = Parameter(default = 0.2)

    def accepts(self):
        return InputFormat(self, format_id='events', extension='.enhanced'), InputFormat(self, format_id='events', extension='.integrated'), InputFormat(self, format_id='events', extension='.types')

    def autosetup(self):
        return IntegrateEventsTask

class IntegrateEventsTask(Task):

    in_events = InputSlot()

    current_events = Parameter()
    overlap_threshold = Parameter()

    def out_integrated_events(self):
        return self.outputfrominput(inputformat='events', stripextension='.enhanced' if self.in_events().path[-3:] == 'ced' else '.types' if self.in_events().path[-3:] == 'pes' else 'integrated', addextension='.more.integrated' if self.in_events().path[-3:] == 'ted' else '.integrated')

    def run(self):

        # read in new events
        with open(self.in_events().path, 'r', encoding = 'utf-8') as file_in:
            new_eventdicts = json.loads(file_in.read())
        new_event_objs = []
        for ed in new_eventdicts:
            eventobj = event.Event()
            eventobj.import_eventdict(ed,txt=False)    
            new_event_objs.append(eventobj)    
        earliest_date = min([event.datetime for event in new_event_objs])
        
        # read in current events
        with open(self.current_events, 'r', encoding = 'utf-8') as file_in:
            current_eventdicts = json.loads(file_in.read())
        current_event_objs = []
        current_event_objs_candidates = []
        for ed in current_eventdicts:
            eventobj = event.Event()
            eventobj.import_eventdict(ed,txt=False)   
            if eventobj.datetime >= earliest_date:
                current_event_objs_candidates.append(eventobj)
            else:
                current_event_objs.append(eventobj)

        # initialize event merger
        merger = event_merger.EventMerger()
        merger.add_events(current_event_objs_candidates)

        # merge before integration
        print('Merging new events before integration; number of events at start:',len(new_event_objs))
        overlap_threshold = float(self.overlap_threshold)
        premerger = event_merger.EventMerger()
        premerger.add_events(new_event_objs)
        premerger.find_merges(overlap_threshold)
        new_events_merged = premerger.return_events()
        print('Done. New events after merge:',len(new_events_merged))

        # integrate each event into the current ones
        print('Starting integrating new events; number of current events:',len(current_event_objs))
        for new_event in new_events_merged:
            merger.find_merge(new_event,overlap_threshold)

        # write merged 
        integrated_events = merger.return_events() + current_event_objs
        print('Done. Number of events after integration:',len(integrated_events))
        out_integrated_events = [event.return_dict(txt=False) for event in integrated_events]
        with open(self.out_integrated_events().path,'w',encoding='utf-8') as file_out:
            json.dump(out_integrated_events,file_out)


@registercomponent
class IntegrateEventDir(StandardWorkflowComponent):

    overlap_threshold = Parameter(default = 0.2)

    def accepts(self):
        return InputFormat(self, format_id='eventdir', extension='.events')

    def autosetup(self):
        return IntegrateEventDirTask

class IntegrateEventDirTask(Task):

    ### task to speed up event integration for sliding window event extraction
    ### make sure that all events in the directory are deduplicated and enhanced before running this task
    ### only files with extension '.enhanced' will be integrated

    in_eventdir = InputSlot()

    overlap_threshold = Parameter()

    def out_integrated_events(self):
        return self.outputfrominput(inputformat='eventdir', stripextension='.events', addextension='events.integrated')

    def run(self):

        # collect all event files with extension '.enhanced'
        enhanced_events = glob.glob(self.in_eventdir().path + '/*.enhanced')

        # initialize
        merger = event_merger.EventMerger()
        overlap_threshold = float(self.overlap_threshold)

        # for each event file
        for eventfile in enhanced_events:
            print('Reading',eventfile)
            with open(eventfile, 'r', encoding = 'utf-8') as file_in:
                current_eventdicts = json.loads(file_in.read())
            new_event_objs = []
            for ed in current_eventdicts:
                eventobj = event.Event()
                eventobj.import_eventdict(ed)
                new_event_objs.append(eventobj)
            # merge before integration
            print('Merging new events before integration; number of events at start:',len(new_event_objs))
            premerger = event_merger.EventMerger()
            premerger.add_events(new_event_objs)
            premerger.find_merges(overlap_threshold)
            new_events_merged = premerger.return_events()
            print('Done. New events after merge:',len(new_events_merged))
            if len(merger.events) == 0:
                merger.add_events(new_events_merged)
            else:
                # integrate each event into the current ones
                print('Starting integrating new events; number of current events:',len(merger.events))
                for new_event in new_events_merged:
                    merger.find_merge(new_event,overlap_threshold)            

        # write merged 
        integrated_events = merger.return_events()
        print('Done. Number of events after integration:',len(integrated_events))
        out_integrated_events = [event.return_dict() for event in integrated_events]
        with open(self.out_integrated_events().path,'w',encoding='utf-8') as file_out:
            json.dump(out_integrated_events,file_out)


################################################################################
###Event merger
################################################################################

@registercomponent
class MergeEvents(StandardWorkflowComponent):

    overlap_threshold = Parameter(default = 0.2)
    similarity_threshold = Parameter(default = 0.7)

    def accepts(self):
        return (
            InputFormat(self, format_id='enhanced_events', extension='.enhanced'),
            InputComponent(self, EnhanceEvents, similarity_threshold=self.similarity_threshold)
        )

    def autosetup(self):
        return MergeEventsTask

class MergeEventsTask(Task):

    in_enhanced_events = InputSlot()

    overlap_threshold = Parameter()

    def out_merged_events(self):
        return self.outputfrominput(inputformat='enhanced_events', stripextension='.enhanced', addextension='.merged')

    def run(self):

        # read in events
        with open(self.in_enhanced_events().path, 'r', encoding = 'utf-8') as file_in:
            eventdicts = json.loads(file_in.read())
        event_objs = []
        for ed in eventdicts:
            eventobj = event.Event()
            eventobj.import_eventdict(ed,txt=False)
            event_objs.append(eventobj)

        # initialize event merger
        print('Merging; number of events at start:',len(event_objs))
        overlap_threshold = float(self.overlap_threshold)
        merger = event_merger.EventMerger()
        merger.add_events(event_objs)
        merger.find_merges(overlap_threshold)
        events_merged = merger.return_events()
        print('Done. number of events after merge:',len(events_merged))

        # write merged 
        out_merged_events = [event.return_dict(txt=False) for event in events_merged]
        with open(self.out_merged_events().path,'w',encoding='utf-8') as file_out:
            json.dump(out_merged_events,file_out)
