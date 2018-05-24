"""Configuration schemas"""
from marshmallow import Schema, fields, validates_schema, ValidationError, \
    post_load
from marshmallow.validate import Length, Range, OneOf

from .source.salesforce import StreamingResourceType


class StrictSchema(Schema):
    """Common schema base class which rejects unknown fields"""

    # pylint: disable=unused-argument
    @validates_schema(pass_original=True)
    def check_unknown_fields(self, data, original_data):
        """Check for the presence and reject unknown fields

        :raise marshmallow.ValidationError: If an unknown field is found
        """
        # get the difference of the loaded and specified fields
        unknown_fields = set(original_data) - set(self.fields)
        # raise an error if any surplus fields are present
        if unknown_fields:
            raise ValidationError('Unknown field', list(unknown_fields))

    # pylint: enable=unused-argument


class PushTopicSchema(StrictSchema):
    """Configuration schema for PushTopic resources"""

    # PushTopic fields are validated according to
    # https://developer.salesforce.com/docs/atlas.en-us.api_streaming.meta/\
    # api_streaming/pushtopic.htm
    Id = fields.String(validate=Length(min=1))
    Name = fields.String(validate=Length(min=1, max=25))
    ApiVersion = fields.Float(validate=Range(min=20.0, max=42.0))
    IsActive = fields.Boolean(default=True)
    NotifyForFields = fields.String(validate=OneOf(["All",
                                                    "Referenced",
                                                    "Select",
                                                    "Where"]))
    Description = fields.String(default=None, validate=Length(max=400))
    NotifyForOperationCreate = fields.Boolean(default=True)
    NotifyForOperationUpdate = fields.Boolean(default=True)
    NotifyForOperationDelete = fields.Boolean(default=True)
    NotifyForOperationUndelete = fields.Boolean(default=True)
    NotifyForOperations = fields.String(validate=OneOf(["All",
                                                        "Create",
                                                        "Extended",
                                                        "Update"]))
    Query = fields.String(validate=Length(min=1, max=1300))

    @validates_schema
    def check_required_fileds(self, data):  # pylint: disable=no-self-use
        """Check for required fields

        :raise marshmallow.ValidationError: If no fields are specified or if \
        only a single non identifier field is specified or multiple fields \
        are specified but they're not enough for a resource definition
        """
        if len(data) == 1:
            unique_id_fields = {"Id", "Name"}
            if not data.keys() & unique_id_fields:
                raise ValidationError("If only a single field is specified "
                                      "it should be a unique identifier like "
                                      "'Id' or 'Name'.")
        elif len(data) > 1:
            required_fields = {"Name", "ApiVersion", "Query"}
            if (data.keys() & required_fields) != required_fields:
                raise ValidationError("If multiple fields are specified it "
                                      "it should be a full resource "
                                      "definition where at least 'Name', "
                                      "'ApiVersion' and 'Query' are required.")
        else:
            raise ValidationError("Either a single fields should be specified "
                                  "which uniquely identifies the resource or "
                                  "multiple fields which can be used to "
                                  "construct the resource.")

    @validates_schema
    def check_api_version(self, data):  # pylint: disable=no-self-use
        """Check for invalid fields for the specified API version

        :raise marshmallow.ValidationError: If any invalid fields found for \
        the specified API version
        """
        # skip validation if the ApiVersion field is not present, which might
        # happen even when it's specified but it's value fails on validation
        if "ApiVersion" not in data:
            return

        # check for the presence of old fields for a newer API version
        if (data["ApiVersion"] >= 29.0 and
                "NotifyForOperations" in data):
            raise ValidationError("'NotifyForOperations' can only be specified"
                                  " for API version 28.0 and earlier.")

        # check for the presence of new fields for an older API version
        elif (data["ApiVersion"] <= 28.0 and
              ("NotifyForOperationCreate" in data or
               "NotifyForOperationDelete" in data or
               "NotifyForOperationUndelete" in data or
               "NotifyForOperationUpdate" in data)):
            raise ValidationError("'NotifyForOperationCreate', "
                                  "'NotifyForOperationDelete', "
                                  "'NotifyForOperationUndelete' and "
                                  "'NotifyForOperationUpdate' can only be "
                                  "specified for API version 29.0 and later.")


class StreamingChannelSchema(StrictSchema):
    """Configuration schema for StreamingChannel resources"""

    # StreamingChannel fields are validated according to
    # https://developer.salesforce.com/docs/atlas.en-us.api_streaming.meta/\
    # api_streaming/streamingChannel.htm
    Id = fields.String(validate=Length(min=1))
    Name = fields.String(validate=Length(min=1, max=80))
    Description = fields.String(default=None, validate=Length(max=255))

    @validates_schema
    def check_required_fileds(self, data):  # pylint: disable=no-self-use
        """Check for required fields

        :raise marshmallow.ValidationError: If no fields are specified or if \
        only a single non identifier field is specified or multiple fields \
        are specified but they're not enough for a resource definition
        """
        if len(data) == 1:
            unique_id_fields = {"Id", "Name"}
            if not data.keys() & unique_id_fields:
                raise ValidationError("If only a single field is specified "
                                      "it should be a unique identifier like "
                                      "'Id' or 'Name'.")
        elif not data:
            raise ValidationError("Either a single fields should be specified "
                                  "which uniquely identifies the resource or "
                                  "multiple fields which can be used to "
                                  "construct the resource.")


class StreamingResourceSchema(StrictSchema):
    """Configuration schema for streaming resources"""

    type = fields.String(required=True, attribute="resource_type",
                         validate=OneOf([_.value for _ in
                                         StreamingResourceType]))
    spec = fields.Dict(required=True, attribute="resource_spec")
    durable = fields.Boolean()

    @post_load
    def load_spec(self, data):
        """Load the spec field with the appropriate schema based on the
        type field"""
        # resource type scpecific schema classes
        schema_map = {
            StreamingResourceType.PUSH_TOPIC: PushTopicSchema,
            StreamingResourceType.STREAMING_CHANNEL: StreamingChannelSchema
        }

        # get the resource type value
        type_name = data[self.fields["type"].attribute]

        # get the schema class for the resource type
        schema_cls = schema_map[type_name]

        # load and update the value of spec field
        spec = data[self.fields["spec"].attribute]
        data[self.fields["spec"].attribute] = schema_cls().load(spec)

        # return the updated data
        return data


class SalesforceOrgSchema(StrictSchema):
    """Configuration schema for a Salesforce organization"""
    consumer_key = fields.String(required=True)
    consumer_secret = fields.String(required=True)
    username = fields.String(required=True)
    password = fields.String(required=True)
    resources = fields.List(fields.Nested(StreamingResourceSchema()),
                            required=True,
                            validate=Length(min=1),
                            attribute="streaming_resource_specs")


class ReplaySchema(StrictSchema):
    """Configuration schema for a Redis replay marker storage"""
    address = fields.Url(schemes=("redis",), required=True)
    key_prefix = fields.String()


class MessageSourceSchema(StrictSchema):
    """Configuration schema for a message source"""
    orgs = fields.Dict(keys=fields.String(),
                       values=fields.Nested(SalesforceOrgSchema()),
                       required=True,
                       validate=Length(min=1),
                       attribute="org_specs")
    replay = fields.Nested(ReplaySchema(), attribute="replay_spec")


class AmqpExchangeSchema(StrictSchema):
    """Configuration schema for declaring AMQP exchanges"""
    exchange_name = fields.String(required=True, validate=Length(min=1))
    type_name = fields.String(required=True, validate=OneOf(["fanout",
                                                             "direct",
                                                             "topic",
                                                             "headers"]))
    passive = fields.Boolean(default=False)
    durable = fields.Boolean(default=False)
    auto_delete = fields.Boolean(default=False)
    no_wait = fields.Boolean(default=False)
    arguments = fields.Dict(allow_none=True)


class AmqpBrokerSchema(StrictSchema):
    """Configuration schema for AMQP connection parameters"""
    host = fields.String(required=True, validate=Length(min=1))
    port = fields.Int(default=None, allow_none=True,
                      validate=Range(min=1, max=(2 ** 16) - 1))
    login = fields.String(default="guest")
    password = fields.String(default="guest")
    virtualhost = fields.String(default="/")
    ssl = fields.Boolean(default=False)
    verify_ssl = fields.Boolean(default=True)
    login_method = fields.String(default="AMQPLAIN")
    insist = fields.Boolean(default=False)
    exchanges = fields.List(fields.Nested(AmqpExchangeSchema()),
                            required=True,
                            validate=Length(min=1),
                            attribute="exchange_specs")


class MessageSinkSchema(StrictSchema):
    """Configuration schema for a message sink"""
    brokers = fields.Dict(keys=fields.String(),
                          values=fields.Nested(AmqpBrokerSchema()),
                          required=True,
                          validate=Length(min=1),
                          attribute="broker_specs")


class RouteSchema(StrictSchema):
    """Configuration schema for route parameters"""
    broker_name = fields.String(required=True, validate=Length(min=1))
    exchange_name = fields.String(required=True)
    routing_key = fields.String(required=True, validate=Length(min=1))
    properties = fields.Dict(keys=fields.String(),
                             values=fields.String(),
                             allow_none=True)


class RoutingRuleSchema(StrictSchema):
    """Configuration schema for routing rule"""
    condition = fields.String(required=True, validate=Length(min=1),
                              attribute="condition_spec")
    route = fields.Nested(RouteSchema(), required=True, attribute="route_spec")


class MessageRouterSchema(StrictSchema):
    """Configuration schema for message router"""
    default_route = fields.Nested(RouteSchema(),
                                  required=True,
                                  allow_none=True,
                                  attribute="default_route_spec")
    rules = fields.List(fields.Nested(RoutingRuleSchema()),
                        attribute="rule_specs")


class ApplicationConfigSchema(StrictSchema):
    """Congiguration schema for setting up the complete rabbit_force
    application"""
    source = fields.Nested(MessageSourceSchema(), required=True)
    sink = fields.Nested(MessageSinkSchema(), required=True)
    router = fields.Nested(MessageRouterSchema(), required=True)
