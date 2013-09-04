import jsonpickle
import re
from django.conf import settings
from django.utils.importlib import import_module
from django.contrib.admindocs.utils import trim_docstring
from django.contrib.admindocs.views import simplify_regex
from django.core.urlresolvers import RegexURLResolver, RegexURLPattern
from rest_framework.views import APIView
from itertools import groupby


class DocumentationGenerator():
    """
    Creates documentation for a list of URL patterns pointing to
    Django REST Framework v.2.0, 2.1.3 APIView instances. The
    documentation is created by looking at the view's docstrings,
    the URL pattern objects, the view's serializers and other properties
    """

    def __init__(self, urlpatterns=None):
        """
        Sets urlpatterns
        urlpatterns -- List of UrlPatterns
        """
        if urlpatterns is None:
            urlpatterns = self.get_url_patterns()
        else:
            urlpatterns = self._flatten_patterns_tree(urlpatterns)
        self.urlpatterns = urlpatterns

    def get_docs(self, as_objects=False):
        """
        Gets the documentation as a list of objects or a JSON string

        as_objects -- (bool) default=False. Set to true to return objects instead of JSON
        """
        docs = self.__process_urlpatterns()
        docs.sort(key=lambda x: x.path)  # Sort by path

        if as_objects:
            return docs
        else:
            return jsonpickle.encode(docs, unpicklable=False)

    def get_url_patterns(self):

        urls = import_module(settings.ROOT_URLCONF)
        patterns = urls.urlpatterns

        api_url_patterns = []
        patterns = self._flatten_patterns_tree(patterns)

        for pattern in patterns:
            # If this is a CBV, check if it is an APIView
            if self._get_api_callback(pattern):
                api_url_patterns.append(pattern)

        # get only unique-named patterns, its, because rest_framework can add
        # additional patterns to distinguish format
        #api_url_patterns = self._filter_unique_patterns(api_url_patterns)
        return api_url_patterns

    def _get_api_callback(self, pattern):
        """
        Verifies that pattern callback is a subclass of APIView, and returns the class
        Handles older django & django rest 'cls_instance'
        """
        if not hasattr(pattern, 'callback'):
            return

        if (hasattr(pattern.callback, 'cls') and issubclass(pattern.callback.cls, APIView)):
            return pattern.callback.cls
        elif (hasattr(pattern.callback, 'cls_instance') and isinstance(pattern.callback.cls_instance, APIView)):
            return pattern.callback.cls_instance

    def _flatten_patterns_tree(self, patterns, prefix=''):
        """
        Uses recursion to flatten url tree.

        patterns -- urlpatterns list
        prefix -- (optional) Prefix for URL pattern
        """
        pattern_list = []
        for pattern in patterns:
            if isinstance(pattern, RegexURLPattern):
                
                pattern.__path = prefix + pattern._regex
                pattern_list.append(pattern)
            elif isinstance(pattern, RegexURLResolver):
                resolver_prefix = pattern._regex
                pattern_list.extend(self._flatten_patterns_tree(pattern.url_patterns, resolver_prefix))
        return pattern_list

    def _filter_unique_patterns(self, patterns):
        """
        Gets only unique patterns by its names
        """
        unique_patterns = []
        # group patterns by its names
        grouped_patterns = groupby(patterns, lambda pattern: pattern.name)
        for name, group in grouped_patterns:
            group_list = list(group)
            # choose from group pattern with shortest regex
            unique = min(group_list, key=lambda pattern: len(pattern.regex.pattern))
            unique_patterns.append(unique)

        return unique_patterns

    def __process_urlpatterns(self):
        """ Assembles ApiDocObject """
        docs = []

        for endpoint in self.urlpatterns:

            # Skip if callback isn't an APIView
            callback = self._get_api_callback(endpoint)
            if callback is None:
                continue

            # Build object and add it to the list
            doc = self.ApiDocObject()
            doc.title = self.__get_title__(endpoint)
            docstring = self.__get_docstring__(endpoint)
            docstring_meta = self.__parse_docstring__(docstring)
            doc.description = docstring_meta['description']
            doc.params = docstring_meta['params']
            doc.exemples = docstring_meta["exemples"]
            doc.name = docstring_meta['name']
            doc.group = docstring_meta['group']
            doc.path = self.__get_path__(endpoint)
            doc.model = self.__get_model__(callback)
            doc.allowed_methods = self.__get_allowed_methods__(callback)
            doc.fields = self.__get_serializer_fields__(callback)
            docs.append(doc)
            del(doc)  # Clean up

        return docs

    def __get_title__(self, endpoint):
        """
        Gets the URL Pattern name and make it the title
        """
        title = ''
        if endpoint.name is None:
            return title

        name = endpoint.name
        title = re.sub('[-_]', ' ', name)

        return title.title()

    def __get_docstring__(self, endpoint):
        """
        Parses the view's docstring and creates a description
        and a list of parameters
        Example of a parameter:

            myVar -- a variable
        """

        if not hasattr(endpoint, 'callback'):
            return

        return endpoint.callback.__doc__

    def __parse_docstring__(self, docstring):

        docstring = self.__trim(docstring)
        split_lines = docstring.split('\n')
        description_line = False
        trimmed = False  # Flag if string needs to be trimmed
        _params = []
        _exemples = []
        name = None
        group = None
        description = docstring

        for line in split_lines:
            needle = line.find("name :")
            if needle  != -1 :
                name = line.split("name :")[1]
            needle = line.find("group :")
            if needle != -1 :
                group = line.split("group :")[1]
            needle = line.find("description :")
            if needle != -1:
                    description = line.split("description :")[1]
                    #while true, add to description
                    description_line = True
            if ' -- ' in line :
                description_line = False
            params = line.split(' -- ')
            if len(params) == 2:
                _params.append([params[0].strip(), params[1].strip()])
            if description_line :
                description = description+line
            if ' ** ' in line :
                _exemples.append({"text":line.split("**")[0],"url":line.split("**")[1]})
        return {'description': description, 'params': _params,'name':name,"group":group,"exemples" : _exemples}


    def __get_path__(self, endpoint):
        """
        Gets the endpoint path based on the regular expression
        pattern of the URL pattern. Cleans out the regex characters
        and replaces with RESTful URL descriptors
        """
        #return simplify_regex(endpoint.regex.pattern)
        return simplify_regex(endpoint.__path)

    def __get_model__(self, endpoint):
        """
        Gets associated model from the view
        """
        api_view = self._get_api_callback(endpoint)
        if hasattr(api_view, 'model'):
            return api_view.model.__name__

    def __get_allowed_methods__(self, callback):
        """
        Gets allowed methods for the API. (ie. POST, PUT, GET)
        """
        if hasattr(callback, '__call__'):
            return callback().allowed_methods
        else:
            return callback.allowed_methods

    def __get_serializer_fields__(self, callback):
        """
        Gets serializer fields if set in the view. Returns dictionaries
        with field properties (read-only, default, min and max length)
        """
        data = []
        if not hasattr(callback, 'get_serializer_class'):
            return data

        if hasattr(callback, '__call__'):
            serializer = callback().get_serializer_class()
        else:
            serializer = callback.get_serializer_class()

        try:
            fields = serializer().get_fields()
        except:
            return

        for name, field in fields.items():
            field_data = {}
            field_data['type'] = self.__camelcase_to_spaces(field.__class__.__name__)

            for key in ('read_only', 'default', 'max_length', 'min_length'):
                if hasattr(field, key):
                    field_data[key] = getattr(field, key)

            data.append({name: field_data})

        return data

    def __trim(self, docstring):
        """
        Trims whitespace from docstring
        """
        return trim_docstring(docstring)

    def __camelcase_to_spaces(self, camel_string):
        CAMELCASE_BOUNDARY = '(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))'
        return re.sub(CAMELCASE_BOUNDARY, ' \\1', camel_string)

    class ApiDocObject(object):
        """ API Documentation Object """
        path = None
        title = None
        description = None
        params = []
        allowed_methods = []
        model = None
        name = None
        groupe = None
        exemples = None
