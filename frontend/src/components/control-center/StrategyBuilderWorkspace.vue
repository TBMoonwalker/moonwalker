<script setup lang="ts">
import { useDialog } from 'naive-ui'

import { useStrategyBuilderWorkspace } from '../../composables/useStrategyBuilderWorkspace'
import StrategyCanvasPanel from './StrategyCanvasPanel.vue'
import StrategyInspectorPanel from './StrategyInspectorPanel.vue'
import StrategyLibraryPanel from './StrategyLibraryPanel.vue'

const dialog = useDialog()

function confirmDelete(strategyName: string): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
        dialog.warning({
            title: 'Delete Strategy',
            content: `Delete custom strategy "${strategyName}"? This cannot be undone.`,
            positiveText: 'Delete',
            negativeText: 'Cancel',
            onPositiveClick: () => resolve(true),
            onNegativeClick: () => resolve(false),
            onClose: () => resolve(false),
            onEsc: () => resolve(false),
            onMaskClick: () => resolve(false),
        })
    })
}

const {
    addNodeFromPalette,
    autoAlignGraph,
    bindReteHost,
    canSave,
    connectSelectedToDecision,
    createBlank,
    deleteSelected,
    draftConflict,
    draftDescription,
    draftName,
    duplicateSelected,
    errorMessage,
    isReadOnly,
    loading,
    nodeTitle,
    palette,
    reteError,
    reteReady,
    saveActiveVersion,
    saveMessage,
    saving,
    selectedDetail,
    selectedNode,
    selectedNodeId,
    selectedSlug,
    selectStrategy,
    setDecisionNode,
    strategies,
    updateIndicatorSelection,
    updateNodeParam,
    updateNodeParamValue,
    updateSelectedInput,
    validateDraft,
    validation,
} = useStrategyBuilderWorkspace({ confirmDelete })
</script>

<template>
    <section class="strategy-builder" aria-labelledby="strategy-builder-title">
        <div class="strategy-status-bar">
            <div>
                <h3 id="strategy-builder-title">Strategy Builder</h3>
                <p>
                    {{ selectedDetail?.name || 'Select a strategy' }}
                    <span v-if="selectedDetail?.active_version" class="mono">
                        v{{ selectedDetail.active_version }}
                    </span>
                </p>
            </div>
            <div class="status-actions">
                <n-tag
                    v-if="selectedDetail"
                    :type="isReadOnly ? 'default' : 'success'"
                    size="small"
                >
                    {{ isReadOnly ? 'Built-in' : 'Custom' }}
                </n-tag>
                <n-tag
                    v-if="validation.status"
                    :type="validation.status === 'valid' ? 'success' : 'error'"
                    size="small"
                >
                    {{ validation.status }}
                </n-tag>
                <n-button
                    secondary
                    :disabled="!selectedDetail || saving"
                    @click="validateDraft"
                >
                    Validate
                </n-button>
                <n-button
                    type="primary"
                    :loading="saving"
                    :disabled="!canSave"
                    @click="saveActiveVersion"
                >
                    Save active version
                </n-button>
                <n-button
                    type="error"
                    secondary
                    :disabled="!selectedDetail || isReadOnly || saving"
                    @click="deleteSelected"
                >
                    Delete
                </n-button>
            </div>
        </div>

        <n-alert
            v-if="errorMessage"
            type="error"
            closable
            @close="errorMessage = null"
        >
            {{ errorMessage }}
        </n-alert>
        <n-alert
            v-if="saveMessage"
            type="success"
            closable
            @close="saveMessage = null"
        >
            {{ saveMessage }}
        </n-alert>
        <n-alert v-if="draftConflict" type="warning">
            This draft is stale. Reload the strategy before saving another
            active version.
        </n-alert>

        <div class="mobile-review-note">
            Graph editing is available on tablet and desktop. This screen keeps
            strategy review and selection readable on phones.
        </div>

        <n-spin :show="loading">
            <div class="strategy-layout">
                <StrategyLibraryPanel
                    class="strategy-library"
                    :strategies="strategies"
                    :palette="palette"
                    :selected-slug="selectedSlug"
                    :read-only="isReadOnly"
                    :saving="saving"
                    :has-selection="Boolean(selectedDetail)"
                    @select="selectStrategy"
                    @create="createBlank"
                    @duplicate="duplicateSelected"
                    @add-node="addNodeFromPalette"
                />

                <div class="strategy-workbench">
                    <StrategyCanvasPanel
                        :detail="selectedDetail"
                        :read-only="isReadOnly"
                        :selected-node-id="selectedNodeId"
                        :rete-error="reteError"
                        :rete-ready="reteReady"
                        :title-for-node="nodeTitle"
                        @host-ready="bindReteHost"
                        @update:selected-node-id="selectedNodeId = $event"
                        @auto-align="autoAlignGraph"
                    />
                    <StrategyInspectorPanel
                        v-model:draft-name="draftName"
                        v-model:draft-description="draftDescription"
                        :detail="selectedDetail"
                        :selected-node="selectedNode"
                        :validation="validation"
                        :read-only="isReadOnly"
                        @validate="validateDraft"
                        @set-decision="setDecisionNode"
                        @connect-decision="connectSelectedToDecision"
                        @update-indicator="updateIndicatorSelection"
                        @update-param="updateNodeParam"
                        @update-param-value="updateNodeParamValue"
                        @update-input="updateSelectedInput"
                    />
                </div>
            </div>
        </n-spin>
    </section>
</template>

<style scoped>
.strategy-builder {
    border: 1px solid var(--mw-color-border);
    border-radius: 8px;
    background: var(--mw-color-surface-raised);
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
}

.strategy-status-bar,
.status-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.status-actions {
    flex-wrap: wrap;
}

.strategy-status-bar h3 {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1rem;
    font-weight: 700;
    margin: 0;
}

.strategy-status-bar p {
    color: var(--mw-color-text-secondary);
    margin: 2px 0 0;
}

.mono {
    font-family: var(--mw-font-mono);
}

.mobile-review-note {
    display: none;
    border: 1px solid var(--mw-color-border);
    border-radius: 6px;
    color: var(--mw-color-text-secondary);
    padding: 10px;
}

.strategy-layout {
    display: grid;
    grid-template-areas: "library workbench";
    grid-template-columns: minmax(230px, 280px) minmax(0, 1fr);
    gap: 12px;
    align-items: start;
    min-height: 0;
}

.strategy-library {
    grid-area: library;
    align-self: stretch;
}

.strategy-workbench {
    grid-area: workbench;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-sm, 6px);
    background: var(--mw-color-surface-panel);
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
}

.strategy-builder :deep(.n-button:not(.n-button--disabled) .n-button__content) {
    font-weight: 700;
    letter-spacing: 0.01em;
}

.strategy-builder
    :deep(.n-button.n-button--primary-type:not(.n-button--disabled) .n-button__content) {
    color: #f7f8f6;
}

.strategy-builder
    :deep(
        .n-button.n-button--secondary:not(.n-button--error-type):not(.n-button--disabled)
            .n-button__content
    ) {
    color: var(--mw-color-text-primary);
}

@media (max-width: 900px) {
    .mobile-review-note {
        display: block;
    }

    .strategy-layout {
        grid-template-areas:
            "library"
            "workbench";
        grid-template-columns: 1fr;
    }
}

@media (max-width: 560px) {
    .strategy-status-bar {
        align-items: flex-start;
        flex-direction: column;
    }

    .status-actions {
        justify-content: flex-start;
        width: 100%;
    }

    .status-actions :deep(.n-button) {
        flex: 1 1 132px;
        min-width: 0;
    }
}
</style>
