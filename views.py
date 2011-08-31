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

from django.shortcuts import render, get_object_or_404
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from ExponWords.ew.models import WordPair, WDict
import ExponWords.ew.models as models
from django.http import Http404, HttpResponseServerError, HttpResponseBadRequest
from django.http import HttpResponse, HttpResponseRedirect
from django.core.urlresolvers import reverse
from django import forms
from django.template import RequestContext
from django.utils.translation import ugettext as _
from django.conf import settings
import datetime
import functools
import json
import random
import re
import sys
import traceback
import unicodedata
import urllib
import urlparse


def index(request):
    user = request.user
    if user.is_authenticated():
        username = user.username
        wdicts = WDict.objects.filter(user=user, deleted=False)
    else:
        username = None
        wdicts = None

    models.log(request, 'index')

    return render(
               request,
               'ew/index.html',
               {'wdicts': wdicts,
                'username': username})


def visualize(request):
    class WDictData(object):
        def __init__(self, name, question_counts):
            object.__init__(self)
            self.name = name
            self.question_counts = question_counts

    dates, wdicts, date_to_question_count = \
        models.calc_future(request.user, 60, datetime.date.today())

    sum_data = WDictData(_('Sum'), [0 for date in dates])
    wdicts_data = [sum_data]
    for wdict in wdicts:
        wdict_data = WDictData(wdict.name, [])
        wdicts_data.append(wdict_data)
        for index, date in enumerate(dates):
            question_count = date_to_question_count[(wdict, date)]
            wdict_data.question_counts.append(question_count)
            sum_data.question_counts[index] += question_count

    return render(
               request,
               'ew/visualize.html',
               {'wdicts_data': wdicts_data,
                'dates': [date.isoformat() for date in dates]})


def options(request):
    return render(
               request,
               'ew/options.html',
               {})


def help(request, lang):
    models.log(request, 'help')
    langs = [langcode for langcode, langname in settings.LANGUAGES]
    if lang in langs:
        return render(
                   request,
                   'ew/help/%s.html' % lang,
                   {'version': models.version})
    else:
        raise Http404


def wdict_access_required(f):

    @login_required
    @functools.wraps(f)
    def wrapper(request, wdict_id, *args, **kw):

        # Get the dictionary; if it does not exist or the user does not own it,
        # send him to page 404
        wdict = get_object_or_404(WDict, pk=wdict_id, user=request.user)

        return f(request, wdict, *args, **kw)

    return wrapper


def word_pair_access_required(f):

    @login_required
    @functools.wraps(f)
    def wrapper(request, word_pair_id, *args, **kw):

        # Get the dictionary; if it does not exist or the user does not own it,
        # send him to page 404
        wp = get_object_or_404(WordPair, pk=word_pair_id, wdict__user=request.user)
        wdict = wp.wdict
        return f(request, wp, wdict, *args, **kw)

    return wrapper


@wdict_access_required
def wdict(request, wdict):
    return render(request,
                  'ew/wdict.html',
                  {'wdict': wdict})


class WordPairForm(forms.ModelForm):
    class Meta:
        model = WordPair
        fields = models.WordPair.get_fields_to_be_edited()


def set_word_pair_form_labels(wdict, form):
    f = form.fields
    f['word_in_lang1'].label = \
        (_('Word in "%(lang)s"') % {'lang': wdict.lang1}) + ':'
    f['word_in_lang2'].label = \
        (_('Word in "%(lang)s"') % {'lang': wdict.lang2}) + ':'
    f['date_added'].label = \
        _('Date of addition') + ':'
    f['date1'].label = \
        _('Date of next practice from "%(lang)s"') % {'lang': wdict.lang1} + ':'
    f['date2'].label = \
        _('Date of next practice from "%(lang)s"') % {'lang': wdict.lang2} + ':'
    f['strength1'].label = \
        _('Strengh of word from "%(lang)s"') % {'lang': wdict.lang1} + ':'
    f['strength2'].label = \
        _('Strengh of word from "%(lang)s"') % {'lang': wdict.lang2} + ':'


@wdict_access_required
def add_word_pair(request, wdict):

    if request.method == 'POST':
        models.log(request, 'add_word_pair')
        form = WordPairForm(request.POST)
        if form.is_valid():

            # creating the new word pair
            wp = form.save(commit=False)
            wdict.wordpair_set.add(wp)
            wp.save()
            wdict.save()

            # saving some fields to the session
            request.session['ew_add_wp_fields'] = wp.get_saved_fields()
            
            # redirection
            wdict_url = reverse('ew.views.add_word_pair', args=[wdict.id])
            return HttpResponseRedirect(wdict_url + '?success=true')
        else:
            message = _('Some fields are invalid.')

    elif request.method == 'GET':
        if request.GET.get('success') == 'true':
            message = _('Word pair added.')
        else:
            message = ''

        data = {'date_added': datetime.date.today(),
                'date1': datetime.date.today(),
                'date2': datetime.date.today(),
                'strength1': 0,
                'strength2': 0}

        saved_field = request.session.get('ew_add_wp_fields', {})
        for field, value in saved_field.items():
            data[field] = value

        form = WordPairForm(data)
    else:
        assert(False)

    set_word_pair_form_labels(wdict, form)
    return render(
               request,
               'ew/add_word_pair.html',
               {'form':  form,
                'message': message,
                'wdict': wdict})


@word_pair_access_required
def edit_word_pair(request, wp, wdict):

    if request.method == 'POST':
        models.log(request, 'edit_word_pair')
        form = WordPairForm(request.POST)
        if form.is_valid():
            for field in models.WordPair.get_fields_to_be_edited():
                setattr(wp, field, form.cleaned_data[field])
            wp.save()
            wdict_url = reverse('ew.views.edit_word_pair', args=[wp.id])
            return HttpResponseRedirect(wdict_url + '?success=true')
        else:
            message = _('Some fields are invalid.')

    elif request.method == 'GET':
        if request.GET.get('success') == 'true':
            message = _('Word pair modified.')
        else:
            message = ''
        form = WordPairForm(instance=wp)

    else:
        assert(False)

    set_word_pair_form_labels(wdict, form)
    return render(
               request,
               'ew/edit_word_pair.html',
               {'form': form,
                'message': message,
                'word_pair': wp,
                'wdict': wdict})


@login_required
def add_wdict(request):

    class AddWDictForm(forms.Form):
        name = forms.CharField(max_length=255,
                               label=_("Name of the dictionary") + ':')
        lang1 = forms.CharField(max_length=255,
                                label=_("Language 1") + ':')
        lang2 = forms.CharField(max_length=255,
                                label=_("Language 2") + ':')

    if request.method == 'POST':
        models.log(request, 'add_wdict')
        form = AddWDictForm(request.POST)
        if form.is_valid():
            wdict = WDict()
            wdict.user = request.user
            wdict.name = form.cleaned_data['name']
            wdict.lang1 = form.cleaned_data['lang1']
            wdict.lang2 = form.cleaned_data['lang2']
            wdict.save()
            wdict_url = reverse('ew.views.wdict', args=[wdict.id])
            return HttpResponseRedirect(wdict_url)
        else:
            message = _('Some fields are invalid.')

    elif request.method == 'GET':
        form = AddWDictForm()
        message = ''

    else:
        assert(False)

    return render(
               request,
               'ew/add_wdict.html',
               {'form':  form,
                'message': message})


def words_to_practice_to_json(words_to_practice):
    result = []
    for wp, direction in words_to_practice:
        result.append([wp.word_in_lang1,
                       wp.word_in_lang2,
                       direction,
                       wp.id,
                       explanation_to_html(wp.explanation)])
    return json.dumps(result)


@wdict_access_required
def practice_wdict(request, wdict):
    text = 'dict: "%s"' % wdict.name
    models.log(request, 'practice_wdict', text)
    words_to_practice = wdict.get_words_to_practice_today()
    json_str = words_to_practice_to_json(words_to_practice)
    return render(request,
                  'ew/practice_wdict.html',
                  {'wdict': wdict,
                   'message': '',
                   'words_to_practice': json_str})


@login_required
def practice(request):
    models.log(request, 'practice')
    words_to_practice = request.session['ew_words_to_practice']
    json_str = words_to_practice_to_json(words_to_practice)
    return render(request,
                  'ew/practice_wdict.html',
                  {'wdict': None,
                   'message': '',
                   'words_to_practice': json_str})


def explanation_to_html(explanation):
    """Escapes the given explanation so that it can be printed as HTML.

    **Argument:**

    - `explanation` (str)

    **Returns:** str
    """

    def insert_nbps(matchobject):
        """Returns the same number of "&nbsp;":s as the number of matched
        characters."""
        spaces = matchobject.group(1)
        return '&nbsp;' * (4 + len(spaces))

    regexp = re.compile(r'^( *)', re.MULTILINE)
    if (len(explanation) > 1) and (explanation[-1] == '\n'):
        explanation = explanation[:-1]
    exp2 = re.sub(regexp, insert_nbps, explanation)
    exp3 = '<br/>'.join(exp2.splitlines())
    return exp3


@login_required
def update_word(request):
    try:

        answer = json.loads(request.POST['answer'])
        word_pair_id = json.loads(request.POST['word_index'])
        direction = json.loads(request.POST['direction'])

        wp = get_object_or_404(WordPair,
                               pk=word_pair_id,
                               wdict__user=request.user)

        if wp.get_date(direction) > datetime.date.today():
            # This update have already been performed
            return HttpResponse(json.dumps('ok'),
                                 mimetype='application/json')

        assert(isinstance(answer, bool))
        if answer:
            # The user knew the answer
            wp.strengthen(direction)
        else:
            # The user did not know the answer
            wp.weaken(direction)
        wp.save()

        return HttpResponse(json.dumps('ok'),
                             mimetype='application/json')
    except Exception, e:
        traceback.print_stack()
        exc_info = sys.exc_info()
        traceback.print_exception(exc_info[0], exc_info[1], exc_info[2])
        raise exc_info[0], exc_info[1], exc_info[2]

def get_word_pairs_to_use(request):

    # Deciding whether:
    # - to use an explicit list of word pair ids (if show_hits is true); or
    # - to rerun the query (if show_hits is false)
    
    source_url = request.POST.get('source_url')
    if source_url:
        url_list = list(urlparse.urlparse(source_url))
        query_list = urlparse.parse_qsl(url_list[4], keep_blank_values=True)
        query_dict = dict(query_list)
        show_hits = ('show_hits' in query_dict)
    else:
        show_hits = True

    # Calculating the list of word pairs

    if show_hits:
        word_pairs = WordPair.objects.filter(wdict__user=request.user,
                                             wdict__deleted=False,
                                             deleted=False)
        word_pairs_to_use = []
        for wp in word_pairs:
            if unicode(wp.id) in request.POST:
                word_pairs_to_use.append(wp)
        return word_pairs_to_use

    else:
        query_text = query_dict['q']
        query_wdict = query_dict['dict']
        query_label = parse_query_label(query_dict['label'])

        word_pairs = \
            search_in_db(request.user, query_wdict, query_label, query_text)
        return word_pairs


@login_required
def action_on_word_pairs(request):

    models.log(request, 'action_on_word_pairs')

    # Select the word pairs to use (i.e. to do the action with)
    word_pairs_to_use = get_word_pairs_to_use(request)

    # Perform the action

    message = None
    action = request.POST.get('action')
    do_action = False
    if action == 'delete':
        do_action = True
    elif action == 'move':
        target_wdict_id = int(request.POST.get('move_word_pairs_wdict'))
        target_wdict = get_object_or_404(WDict, pk=target_wdict_id,
                                         user=request.user)
        do_action = True
    elif action in ('add_labels', 'remove_labels', 'set_labels'):
        labels = request.POST.get(action + '-labels')
        do_action = True
    elif action == 'set_dates_strengths':
        try:
            values = {}
            fields = ('date1', 'date2', 'strength1', 'strength2')
            for field in fields:
                raw_value = request.POST.get(field, '').strip()
                if raw_value == '':
                    value = None
                elif field.startswith('date'):
                    value = models.parse_date(raw_value)
                elif field.startswith('strength'):
                    value = int(raw_value)
                else:
                    assert(False)
                values[field] = value
            do_action = True
        except ValueError:
            message = _('Please specify the fields correctly!')
    elif action == 'shift_days':
        try:
            days = datetime.timedelta(days=int(request.POST.get('days')))
            do_action = True
        except ValueError:
            message = _('Please specify the number of days!')
    elif action == 'practice':
        # We don't do an action to the words themselves
        practice_scope = request.POST.get('practice_scope')
        do_action = False
    else:
        message = _('Action not recognized') + ': ' + str(action)

    if do_action:
        for wp in word_pairs_to_use:
            if action == 'delete':
                wp.deleted = True
            elif action == 'move':
                wp.wdict = target_wdict
            elif action == 'add_labels':
                wp.add_labels(labels)
            elif action == 'remove_labels':
                wp.remove_labels(labels)
            elif action == 'set_labels':
                wp.set_labels(labels)
            elif action == 'set_dates_strengths':
                for field in fields:
                    if values[field] is not None:
                        setattr(wp, field, values[field])
            elif action == 'shift_days':
                wp.date1 += days
                wp.date2 += days
            wp.save()

    # Redirect the user to the search page where which he issue the action

    source_url = request.POST.get('source_url')

    if action == 'practice':
        today = datetime.date.today()
        words_to_practice = []
        for wp in word_pairs_to_use:
            if (practice_scope == 'all' or wp.date1 <= today):
                words_to_practice.append((wp, 1))
            if (practice_scope == 'all' or wp.date2 <= today):
                words_to_practice.append((wp, 2))
        random.shuffle(words_to_practice)

        request.session['ew_words_to_practice'] = words_to_practice
        redirect_url = reverse('ew.views.practice', args=[])

    elif source_url:
        if message is None:
            word_count = len(word_pairs_to_use)
            if word_count == 0:
                message = _('No word pair modified.')
            elif word_count == 1:
                message = _('1 word pair modified.')
            else:
                message = _('%(count)s word pairs modified.') % {'count': word_count}

        redirect_url = (source_url +
                        '&message=' +
                        urllib.quote_plus(message.encode("utf-8")))
    else:
        redirect_url = reverse('ew.views.index', args=[])

    return HttpResponseRedirect(redirect_url)


def CreateImportWordPairsForm(wdict):

    class ImportForm(forms.Form):
         text = forms.CharField(widget=forms.Textarea,
                                label=_("Text") + ':')
         labels = forms.CharField(label=_("Labels") + ':',
                                 required=False)

    return ImportForm


def import_word_pairs(request, wdict, import_fun, page_title, help_text):

    ImportForm = CreateImportWordPairsForm(wdict)
    if request.method == 'POST':
        models.log(request, 'import_word_pairs', page_title)
        form = ImportForm(request.POST)
        if form.is_valid():
            try:
                word_pairs = import_fun(form.cleaned_data['text'], wdict)
                labels = form.cleaned_data['labels']
                for wp in word_pairs:
                    wp.add_labels(labels)
                    wp.save()
                message = _('Word pairs added.')
                form = None
            except Exception, e:
                message = _('Error: ') + unicode(e)
        else:
            message = _('Some fields are invalid.')
    else:
        form = None
        message = ''

    if form is None:
        form = ImportForm()

    return render(
               request,
               'ew/import_word_pairs.html',
               {'form':  form,
                'help_text': help_text,
                'message': message,
                'wdict': wdict,
                'page_title': page_title})


@wdict_access_required
def import_word_pairs_from_text(request, wdict):

    page_title = _('Import word pairs from text')
    help_text = ""
    return import_word_pairs(request, wdict, models.import_textfile,
                             page_title, help_text)


@wdict_access_required
def import_word_pairs_from_tsv(request, wdict):

    page_title = _('Import word pairs from tab-separated values')
    help_text = _("Write one word per line. Each word should contain two or "
                "three fields: word in the first language; word in the "
                "second language; explanation. The last one is optional. "
                "The fields should be separated by a TAB character. If a "
                "spreadsheet is opened in as spreadsheet editor application "
                "(such as LibreOffice, OpenOffice.org or Microsoft Excel), "
                "and it contains these three columns, which are copied and "
                "pasted here, then it will have exactly this format.")
    return import_word_pairs(request, wdict, models.import_tsv,
                             page_title, help_text)


@wdict_access_required
def export_word_pairs_to_text(request, wdict):
    models.log(request, 'export_word_pairs_to_text')
    text = models.export_textfile(wdict)
    return render(
               request,
               'ew/export_wdict_as_text.html',
               {'wdict': wdict,
                'text': text})


def CreateDeleteWDictForm(wdict):
    label = (_('Are you sure that you want to delete dictionary "%(wdict)s"?') %
             {'wdict': wdict.name})
    class DeleteWDictForm(forms.Form):
         sure = forms.BooleanField(label=label, required=False)
    return DeleteWDictForm


@wdict_access_required
def delete_wdict(request, wdict):

    DeleteWDictForm = CreateDeleteWDictForm(wdict)
    if request.method == 'POST':
        models.log(request, 'delete_wdict')
        form = DeleteWDictForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['sure']:
                wdict.deleted = True
                wdict.save()
                message = _('Dictionary deleted.')
                form = None
            else:
                message = _('Please check in the "Are you sure" checkbox if '
                            'you really want to delete the dictionary.')
        else:
            message = _('Some fields are invalid.')
    else:
        form = None
        message = ''

    if form is None:
        form = DeleteWDictForm()

    return render(
               request,
               'ew/delete_wdict.html',
               {'form':  form,
                'message': message,
                'wdict': wdict})


def bad_unicode_to_str(u):
    """This function converts a unicode object that actually contains UTF-8
    encoded text (instead of unicode characters) to a UTF-8 encoded string."""
    return ''.join([chr(ord(ch)) for ch in u])


def remove_query_param(url, param_name):
    url_list = list(urlparse.urlparse(url))
    query_list = urlparse.parse_qsl(url_list[4], keep_blank_values=True)
    new_query_list = [(k, bad_unicode_to_str(v))
                      for k, v in query_list if k != param_name]
    new_raw_query = urllib.urlencode(new_query_list)
    url_list[4] = new_raw_query
    new_url = urlparse.urlunparse(url_list)
    return new_url


def normalize_string(s):
    # Code copied from: http://stackoverflow.com/questions/517923/what-is-the-best-way-to-remove-accents-in-a-python-unicode-string/518232#518232
    return ''.join((c for c in unicodedata.normalize('NFD', s.lower())
                    if unicodedata.category(c) != 'Mn'))

class LenientChoiceField(forms.ChoiceField):

    def __init__(self, *args, **kw):
        super(LenientChoiceField, self).__init__(*args, **kw)

    def validate(self, value):
        super(forms.ChoiceField, self).validate(value)
        if value and not self.valid_value(value):
            self.is_really_valid = False
        else:
            self.is_really_valid = True


def parse_query_label(query_label_raw):
    if query_label_raw in ('', 'all'):
        return None
    else:
        return query_label_raw

def search_in_db(user, query_wdict, query_label, query_text):
    if query_wdict in ('', 'all'):
        all_word_pairs = WordPair.objects.filter(wdict__user=user,
                                                 wdict__deleted=False,
                                                 deleted=False)
    else:
        wdict_id = int(query_wdict)
        wdict = get_object_or_404(WDict, pk=wdict_id, user=user)
        all_word_pairs = WordPair.objects.filter(wdict=wdict,
                                                 deleted=False)
    word_pairs = []
    query_words = [normalize_string(query_word)
                   for query_word in query_text.split()]
    query_items = []
    for query_word in query_words:
        if query_word.startswith('label:'):
            query_items.append(('label', query_word[6:]))
        else:
            query_items.append(('text', query_word))
            
    for wp in all_word_pairs:
        wp_matches_all = True
        if ((query_label is not None) and
            (query_label not in wp.get_label_set())):
            # We require a certain label but wp does not have it
            continue

        for query_item_type, query_item_value in query_items:
            query_item_matches = False
            if query_item_type == 'label':
                labels = normalize_string(unicode(wp.labels))
                query_item_matches = (labels.find(query_item_value) != -1)
            else: # query_item_type == 'text'
                for field in models.WordPair.get_fields_to_be_edited():
                    field_text = normalize_string(unicode(getattr(wp, field)))
                    if (field_text.find(query_item_value) != -1):
                        query_item_matches = True
                        break
            if not query_item_matches:
                wp_matches_all = False
                break
        if wp_matches_all:
            word_pairs.append(wp)
    return word_pairs


@login_required
def search(request):

    wdicts = WDict.objects.filter(user=request.user, deleted=False)
    wdict_choices = [(wdict.id, wdict.name) for wdict in wdicts]
    wdict_choices_full = [('all', _('All'))] + wdict_choices

    labels = sorted(models.get_labels(request.user))
    label_choices_full = ([('all', _('All'))] + 
                          [(label, label) for label in labels])

    class SearchForm(forms.Form):
        q = forms.CharField(max_length=255,
                            label=_('Search expression') + ':',
                            required=False)
        dict = forms.ChoiceField(choices=wdict_choices_full,
                                 label=_('Dictionary') + ':',
                                 required=False)
        label = LenientChoiceField(choices=label_choices_full,
                                   label=_('Label') + ':',
                                   required=False)
        show_hits = forms.BooleanField(label=_('Show hits') + ':',
                                         required=False)

    if request.method != 'GET':
        raise Http404

    form = SearchForm(request.GET)
    if not form.is_valid():
        raise Http404

    message = request.GET.get('message', '')
    wdict = None
    query_text = form.cleaned_data['q']
    query_wdict = form.cleaned_data['dict']
    query_label = parse_query_label(form.cleaned_data['label'])
    show_hits = form.cleaned_data['show_hits']

    # If we don't have a 'q' parameter, we will show the basic search page. If
    # we do have one, we will perform the search, even if it is empty.

    if 'q' not in request.GET:
        if query_wdict in ('', 'all'):
            form = SearchForm({'show_hits': True})
        else:
            wdict = get_object_or_404(WDict, pk=int(query_wdict),
                                      user=request.user)
            form = SearchForm({'dict': query_wdict, 'show_hits': True})
        word_pairs_and_exps = None
        result_exists = False
        hits_count = 0
        show_hits = False

    else:
        word_pairs = \
            search_in_db(request.user, query_wdict, query_label, query_text)

        result_exists = True
        hits_count = len(word_pairs)
        if show_hits:
            word_pairs_and_exps = [(wp, explanation_to_html(wp.explanation))
                                   for wp in word_pairs]
        else:
            word_pairs_and_exps = []

    source_url = remove_query_param(request.get_full_path(), 'message')

    return render(
               request,
               'ew/search.html',
               {'form': form,
                'message': message,
                'wdict': wdict,
                'word_pairs_and_exps': word_pairs_and_exps,
                'source_url': source_url,
                'result_exists': result_exists,
                'show_hits': show_hits,
                'hits_count': hits_count,
                'wdict_choices': wdict_choices})
