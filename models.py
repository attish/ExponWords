# This file is part of ExponWords.
#
# ExponWords is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# ExponWords is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# ExponWords.  If not, see <http://www.gnu.org/licenses/>.

# Copyright (C) 2011 Csaba Hoch

import datetime
import random
import re
from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import ugettext as _


version = '0.8.1'


class EWUser(models.Model):

    user = models.OneToOneField(User, primary_key=True)
    lang = models.CharField(max_length=10)

    def __unicode__(self):
        return self.user.username


class WDict(models.Model):

    # WDict = word dictionary (as opposed to the dictionary data type which is
    # an "object dictionary")

    user = models.ForeignKey(User)
    name = models.CharField(max_length=255) # the name of the dictionary
    lang1 = models.CharField(max_length=255)
    lang2 = models.CharField(max_length=255)
    deleted = models.BooleanField(default=False)

    def __unicode__(self):
        return self.name

    def get_words_to_practice_today(self):
        today = datetime.date.today()
        result = []
        for wp in self.wordpair_set.filter(deleted=False):
            if wp.date1 <= today:
                result.append((wp, 1))
            if wp.date2 <= today:
                result.append((wp, 2))
        random.shuffle(result)
        return result


class WordPair(models.Model):

    # each word pair belongs to a dictionary
    wdict = models.ForeignKey(WDict)

    # the word in the first/second language:
    word_in_lang1 = models.CharField(max_length=255)
    word_in_lang2 = models.CharField(max_length=255)

    # strengths of the word
    strength1 = models.IntegerField(default=0)
    strength2 = models.IntegerField(default=0)

    # dates of the next practice
    date_added = models.DateField()
    date1 = models.DateField()
    date2 = models.DateField()

    # explanation, examples, comments, etc.
    explanation = models.TextField(blank=True)

    # labels
    labels = models.CharField(max_length=255, blank=True)

    # whether the word pair is deleted or not
    deleted = models.BooleanField(default=False)

    def save(self):
        self.normalize()
        return models.Model.save(self)

    def normalize(self):
        self.word_in_lang1 = self.word_in_lang1.strip()
        self.word_in_lang2 = self.word_in_lang2.strip()
        self.explanation = self.explanation.rstrip()
        self.normalize_labels()

    def __unicode__(self):
        return ('<%s -- %s>' %
                (repr(self.word_in_lang1), repr(self.word_in_lang2)))

    def get_strength(self, direction):
        if direction == 1:
            return self.strength1
        else:
            return self.strength2

    def set_strength(self, direction, value):
        if direction == 1:
            self.strength1 = value
        else:
            self.strength2 = value

    def get_date(self, direction):
        if direction == 1:
            return self.date1
        else:
            return self.date2

    def set_date(self, direction, value):
        if direction == 1:
            self.date1 = value
        else:
            self.date2 = value

    @staticmethod
    def next_date(strength, date):
        if strength < 0:
            strength = 0
        return date + datetime.timedelta(2 ** strength)

    def strengthen(self, direction):
        strength = self.get_strength(direction)
        self.set_date(direction,
                      self.next_date(strength, datetime.date.today()))
        self.set_strength(direction, self.get_strength(direction) + 1)

    def weaken(self, direction):
        self.set_date(direction, datetime.date.today())
        new_strength = min(self.get_strength(direction), 0)
        self.set_strength(direction, new_strength)

    @staticmethod
    def get_label_set_from_str(s):
        return set(unicode(s).split())

    def get_label_set(self):
        return self.get_label_set_from_str(self.labels)

    def set_label_set(self, label_set):
        self.labels = ' '.join(sorted(label_set))

    def normalize_labels(self):
        self.set_label_set(self.get_label_set())

    def add_labels(self, labels):
        self.set_label_set(self.get_label_set() |
                           self.get_label_set_from_str(labels))

    def remove_labels(self, labels):
        self.set_label_set(self.get_label_set() -
                           self.get_label_set_from_str(labels))

    def set_labels(self, labels):
        self.set_label_set(self.get_label_set_from_str(labels))

    @staticmethod
    def get_fields_to_be_edited():
        return ('word_in_lang1',
                'word_in_lang2',
                'explanation',
                'labels',
                'date_added',
                'date1',
                'date2',
                'strength1',
                'strength2')

    @staticmethod
    def get_fields_to_be_saved():
        return ('labels',
                'date1',
                'date2',
                'strength1',
                'strength2')

    def get_saved_fields(self):
        saved_fields = {}
        for field in self.get_fields_to_be_saved():
            saved_fields[field] = getattr(self, field)
        return saved_fields


class EWException(Exception):
    """A very simple exception class used."""

    def __init__(self, value):
        """Constructor.

        **Argument:**

        - `value` (object) -- The reason of the error.
        """
        Exception.__init__(self)
        self.value = value

    def __unicode__(self):
        """Returns the string representation of the error reason.

        **Returns:** str
        """

        value = self.value
        if isinstance(value, unicode):
            return value
        elif isinstance(value, str):
            return unicode(value)
        else:
            return repr(value)


def create_add_word_pairs(wdict, word_pairs):
    for wp in word_pairs:
        wdict.wordpair_set.add(wp)
        wp.save()
        wdict.save()


def get_labels(user):
    all_word_pairs = WordPair.objects.filter(wdict__user=user,
                                             wdict__deleted=False,
                                             deleted=False)
    labels = set()
    for wp in all_word_pairs:
        labels.update(unicode(wp.labels).split())
    return labels


def import_textfile(s, wdict):
    """Adds words from a text file to a dictionary.

    Arguments:
    - s (str)
    - wdict (WDict)
    """

    i = 1
    word_pairs = []
    for line in s.splitlines():
        line = line.rstrip()
        if (line == '') or (line[0] == ' '):
            # This line is part of an explanation.
            if len(word_pairs) != 0:
                line = re.sub('^ {1,4}', '', line) # removing prefix spaces
                word_pairs[-1].explanation += line + '\n'
            elif line == '':
                pass
            else:
                msg = (_('Line %(linenumber)s should not have spaces in '
                         'the beginning: %(line)s') %
                       {'linenumber': i, 'line': line})
                raise EWException(msg)
        else:
            # This line contains a word pair.
            strength_date_regexp = '<(-?\d+) +(\d\d\d\d)-(\d\d)-(\d\d)>'
            regexp = (r'^(\{(\d+)\})? *(.*?) -- (.*?)' +
                      '( ' + strength_date_regexp * 2 + ')?' +
                      '$')
            r = re.search(regexp, line)
            if r is None:
                msg = (_('Line %(linenumber)s is incorrect: %(line)s') %
                       {'linenumber': i, 'line': line})
                raise EWException(msg)

            wp = WordPair()
            word_pairs.append(wp)

            wp.word_in_lang1 = r.group(3)
            wp.word_in_lang2 = r.group(4)
            wp.explanation = ''
            if r.group(5) is not None:
                wp.date_added = datetime.date.today()
                wp.date1 = datetime.date(int(r.group(7)),
                                         int(r.group(8)),
                                         int(r.group(9)))
                wp.date2 = datetime.date(int(r.group(11)),
                                         int(r.group(12)),
                                         int(r.group(13)))
                wp.strength1 = int(r.group(6))
                wp.strength2 = int(r.group(10))
            else:
                wp.date_added = datetime.date.today()
                wp.date1 = datetime.date.today()
                wp.date2 = datetime.date.today()
                wp.strength1 = 0
                wp.strength2 = 0

        i += 1

    create_add_word_pairs(wdict, word_pairs)
    return word_pairs

def import_tsv(s, wdict):
    """Adds words from a text of tab-separeted values to a dictionary.

    Arguments:
    - s (str)
    - wdict (WDict)
    """

    i = 1
    word_pairs = []
    for line in s.splitlines():
        line = line.strip()
        if (line == ''):
            continue

        fields = line.split('\t')
        if len(fields) < 2:
            msg = (_('Not enough fields in line %(linenumber)s: %(line)s') %
                   {'linenumber': i, 'line': line})
            raise EWException(msg)
        elif 2 <= len(fields) <= 3:
            wp = WordPair()
            wp.word_in_lang1 = fields[0]
            wp.word_in_lang2 = fields[1]
            if len(fields) == 3:
                wp.explanation = fields[2]
            wp.date1 = datetime.date.today()
            wp.date2 = datetime.date.today()
            wp.date_added = datetime.date.today()
            word_pairs.append(wp)
        else:
            msg = (_('Too many fields in line %(linenumber)s: %(line)s') %
                   {'linenumber': i, 'line': line})
            raise EWException(msg)

        i += 1

    create_add_word_pairs(wdict, word_pairs)
    return word_pairs


def export_textfile(wdict):
    """Prints a dictionary in the old text format.

    Arguments:
    - wdict (WDict)

    Returns: str
    """

    result = []
    for wp in wdict.wordpair_set.filter(deleted=False):
        result.append(
            '%s -- %s <%s %s><%s %s>\n' %
            (wp.word_in_lang1,
             wp.word_in_lang2,
             str(wp.strength1),
             str(wp.date1),
             str(wp.strength2),
             str(wp.date2)))
        for expl_line in wp.explanation.splitlines():
            if expl_line != '':
                result.append('    ')
                result.append(expl_line)
            result.append('\n')
    return ''.join(result)


class EWLogEntry(models.Model):

    datetime = models.DateTimeField()
    action = models.TextField()
    user = models.ForeignKey(User, blank=True, null=True)
    username = models.TextField(blank=True)
    text = models.TextField(blank=True)
    ipaddress = models.TextField(blank=True)


def log(request, action, text=''):

    logentry = EWLogEntry()
    logentry.datetime = datetime.datetime.now()
    try:
        logentry.action = action
        logentry.ipaddress = (request.META.get('REMOTE_ADDR' , '') + ', ' +
                              request.META.get('HTTP_X_FORWARDED_FOR', ''))
        if request.user.is_authenticated():
            logentry.user = request.user
            logentry.username = request.user.username

        logentry.text = text
    except Exception, e:
        logentry.action = 'Logging failed'
    logentry.save()

def parse_date(s):
    return datetime.datetime.strptime(s, '%Y-%m-%d')


##### show future #####


def incr_wcd(wcd, wdict, strength, date, count):
    strength_to_word_count = wcd.setdefault((wdict, date), {})
    try:
        strength_to_word_count[strength] += count
    except KeyError:
        strength_to_word_count[strength] = count


def get_initial_word_counts_dict(user, start_date):
    """
    Returns: wdicts, {(wdict, date): {strength: word_count}}
    """

    def add_wp(wcd, wdict, strength, date):
        if (start_date is not None) and (date < start_date):
            date = start_date
        incr_wcd(wcd, wdict, strength, date, 1)
        
    wcd = {}
    wdicts = WDict.objects.filter(user=user, deleted=False)
    word_pairs = WordPair.objects.filter(wdict__user=user,
                                         wdict__deleted=False,
                                         deleted=False)
    for wp in word_pairs:
        add_wp(wcd, wp.wdict, wp.strength1, wp.date1)
        add_wp(wcd, wp.wdict, wp.strength2, wp.date2)
    return wdicts, wcd


def calc_future(user, days_count, start_date):
    """
    Returns: [date], [WDict], {(WDict, date): question_count}
    """

    dates = [start_date + datetime.timedelta(i)
             for i in range(days_count)]

    wdicts, wcd = get_initial_word_counts_dict(user, start_date)

    date_to_question_count = {} # {(wdict, date): question_count}
    for date in dates:
        for wdict in wdicts:
            strength_to_word_count = wcd.pop((wdict, date), {})
            question_count = 0
            for strength, word_count in strength_to_word_count.items():
                question_count += word_count
                new_date = WordPair.next_date(strength, date)
                incr_wcd(wcd, wdict, strength + 1, new_date, word_count)
            date_to_question_count[(wdict, date)] = question_count

    return dates, wdicts, date_to_question_count
