import graphene
from dagster import check
from dagster.core.execution.backfill import BulkActionStatus, PartitionBackfill
from dagster.core.storage.pipeline_run import PipelineRunsFilter

from .errors import (
    GrapheneInvalidOutputError,
    GrapheneInvalidStepError,
    GraphenePartitionSetNotFoundError,
    GraphenePipelineNotFoundError,
    GraphenePipelineRunConflict,
    GraphenePythonError,
    create_execution_params_error_types,
)
from .pipelines.config import GraphenePipelineConfigValidationInvalid
from .util import non_null_list

pipeline_execution_error_types = (
    GrapheneInvalidStepError,
    GrapheneInvalidOutputError,
    GraphenePipelineConfigValidationInvalid,
    GraphenePipelineNotFoundError,
    GraphenePipelineRunConflict,
    GraphenePythonError,
) + create_execution_params_error_types


class GraphenePartitionBackfillSuccess(graphene.ObjectType):
    backfill_id = graphene.NonNull(graphene.String)
    launched_run_ids = graphene.List(graphene.String)

    class Meta:
        name = "PartitionBackfillSuccess"


class GraphenePartitionBackfillResult(graphene.Union):
    class Meta:
        types = (
            GraphenePartitionBackfillSuccess,
            GraphenePartitionSetNotFoundError,
        ) + pipeline_execution_error_types
        name = "PartitionBackfillResult"


class GrapheneBulkActionStatus(graphene.Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    class Meta:
        name = "BulkActionStatus"


class GraphenePartitionBackfill(graphene.ObjectType):
    class Meta:
        name = "PartitionBackfill"

    backfillId = graphene.NonNull(graphene.String)
    status = graphene.NonNull(GrapheneBulkActionStatus)
    isPersisted = graphene.NonNull(graphene.Boolean)
    numRequested = graphene.Int()
    numTotal = graphene.Int()
    fromFailure = graphene.Boolean()
    reexecutionSteps = graphene.List(graphene.NonNull(graphene.String))
    runs = graphene.Field(
        non_null_list("dagster_graphql.schema.pipelines.pipeline.GraphenePipelineRun"),
        limit=graphene.Int(),
    )

    def __init__(self, backfill_id, backfill_job=None):
        self._backfill_id = check.str_param(backfill_id, "backfill_id")
        self._backfill_job = check.opt_inst_param(backfill_job, "backfill_job", PartitionBackfill)

        super().__init__(
            backfillId=backfill_id,
            isPersisted=bool(backfill_job),
            status=backfill_job.status if backfill_job else BulkActionStatus.COMPLETED,
            numTotal=len(backfill_job.partition_names) if backfill_job else None,
            fromFailure=bool(backfill_job.from_failure) if backfill_job else False,
            reexecutionSteps=backfill_job.reexecution_steps if backfill_job else None,
        )

    def resolve_runs(self, graphene_info, **kwargs):
        from .pipelines.pipeline import GraphenePipelineRun

        filters = PipelineRunsFilter.for_backfill(self._backfill_id)
        return [
            GraphenePipelineRun(r)
            for r in graphene_info.context.instance.get_runs(
                filters=filters,
                limit=kwargs.get("limit"),
            )
        ]

    def resolve_numRequested(self, graphene_info):
        filters = PipelineRunsFilter.for_backfill(self._backfill_id)
        run_count = graphene_info.context.instance.get_runs_count(filters)
        if not self._backfill_job:
            return run_count
        if self._backfill_job.status == BulkActionStatus.COMPLETED:
            return len(self._backfill_job.partition_names)

        checkpoint = self._backfill_job.last_submitted_partition_name
        return max(
            run_count,
            self._backfill_job.partition_names.index(checkpoint) + 1
            if checkpoint and checkpoint in self._backfill_job.partition_names
            else 0,
        )


class GraphenePartitionBackfillOrError(graphene.Union):
    class Meta:
        types = (GraphenePartitionBackfill, GraphenePythonError)
        name = "PartitionBackfillOrError"
